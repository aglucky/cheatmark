from fastapi import FastAPI, HTTPException
import subprocess
import os
from string import Template
from pydantic import BaseModel
from typing import Literal, Optional
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

OUTPUT_DIR = "test"

app = FastAPI(
    title="CheatMark", description="Convert markdown files to PDF cheat sheets"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Add your frontend URL
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


class TemplateConfig(BaseModel):
    fontSize: str = "5pt"
    lineSpacing: str = "5pt"
    columnNum: str = "3"
    orientation: Literal["landscape", "portrait"] = "landscape"
    columnSep: str = "1mm"
    upDown: str = "1mm"
    leftRight: str = "1mm"


class ConversionRequest(BaseModel):
    content: str
    template_config: Optional[TemplateConfig] = None


class ConversionResponse(BaseModel):
    status: str
    message: str
    output_path: str
    template_config: dict


def getFileName(path: str) -> str:
    return os.path.basename(path).split(".")[0]


def get_template_path(file_name: str) -> str:
    # return os.path.join("/template", file_name) # for development
    return os.path.join("/app/template", file_name)


def render_latex(
    file_name: str, template_config: TemplateConfig, errors: list[str]
) -> list[str]:
    pandoc_command = [
        "pandoc",
        "--from=markdown",
        f"--output={file_name}_temp.tex",
        f"{file_name}.md",
    ]
    result = subprocess.run(
        pandoc_command, capture_output=True, text=True, encoding="utf-8", cwd=OUTPUT_DIR
    )
    if result.returncode != 0:
        errors.append(f"Pandoc error: {result.stderr}")

    if not os.path.exists(os.path.join(OUTPUT_DIR, f"{file_name}_temp.tex")):
        errors.append(f"Pandoc failed to create file {file_name}.tex")
        return errors

    create_final_tex(file_name, template_config, errors)
    return errors


def create_final_tex(
    file_name: str, template_config: TemplateConfig, errors: list[str]
) -> list[str]:
    try:
        with open(
            os.path.join(OUTPUT_DIR, f"{file_name}.tex"), "w", encoding="utf-8"
        ) as final_tex:
            header_path = get_template_path("HEADER.txt")
            try:
                with open(header_path, "r", encoding="utf-8") as header_file:
                    header_template = Template(header_file.read())
                    header_data = template_config.model_dump()
                    final_tex.write(header_template.substitute(header_data))
            except FileNotFoundError:
                errors.append(f"Template file not found: {header_path}")
                return errors

            try:
                with open(
                    os.path.join(OUTPUT_DIR, f"{file_name}_temp.tex"), "r", encoding="utf-8"
                ) as content_file:
                    final_tex.write(content_file.read())
            except FileNotFoundError:
                errors.append(f"Content file not found: {file_name}.tex")
                return errors

            footer_path = get_template_path("FOOTER.txt")
            try:
                with open(footer_path, "r", encoding="utf-8") as footer_file:
                    final_tex.write(footer_file.read())
            except FileNotFoundError:
                errors.append(f"Template file not found: {footer_path}")
                return errors

    except Exception as e:
        errors.append(f"File operation error: {str(e)}")

    return errors


def render_pdf(file_name: str, errors: list[str]) -> list[str]:
    pdflatex_command = [
        "pdflatex",
        "-synctex=1",
        "-interaction=nonstopmode",
        "-file-line-error",
        f"{file_name}.tex",
    ]

    result = subprocess.run(
        pdflatex_command,
        cwd=OUTPUT_DIR,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )

    if result.returncode != 0:
        error_output = result.stderr + "\n" + result.stdout
        error_msg = (
            error_output.strip()
            if error_output.strip()
            else "PDFLatex failed without error output"
        )

        full_error = (
            f"PDFLatex Error (Return Code {result.returncode}):\n"
            f"Input File: {file_name}.tex\n"
            f"Error Details:\n{error_msg}"
        )
        errors.append(full_error)

    if not os.path.exists(os.path.join(OUTPUT_DIR, f"{file_name}.pdf")):
        raise Exception(f"PDFLatex failed to create file {file_name}.pdf. Errors: {errors}")

    return errors


def clean_up(path: str) -> None:
    try:
        full_path = os.path.join(OUTPUT_DIR, path)
        if os.path.exists(f"{full_path}_temp.pdf"):
            os.remove(f"{full_path}_temp.pdf")

        if os.path.exists(f"{full_path}_temp.tex"):
            os.remove(f"{full_path}_temp.tex")

        dir_path = os.path.dirname(full_path)
        base_name = os.path.basename(path)
        for file in os.listdir(dir_path):
            if file.startswith(f"{base_name}_temp") and file.endswith(
                (".aux", ".log", ".out", ".synctex.gz")
            ):
                os.remove(os.path.join(dir_path, file))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup error: {str(e)}")


@app.post("/convert")
async def convert_to_pdf(request: ConversionRequest):
    if not request.content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    # Generate a unique filename for this conversion
    file_name = f"cheatsheet_{os.urandom(4).hex()}"  # Generate random filename
    template_config = request.template_config or TemplateConfig()
    output_pdf = os.path.join(OUTPUT_DIR, f"{file_name}.pdf")
    
    # Write the content to a temporary markdown file
    md_file_path = os.path.join(OUTPUT_DIR, f"{file_name}.md")
    try:
        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(request.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write markdown file: {str(e)}")

    errors = []
    try:
        errors = render_latex(file_name, template_config, errors)
        errors = render_pdf(file_name, errors)
    except Exception as e:
        errors.append(f"Conversion error: {str(e)}")
    
    clean_up(file_name)

    if errors:
        error_log_path = os.path.join(OUTPUT_DIR, f"{file_name}_errors.log")
        with open(error_log_path, 'w') as error_log:
            for error in errors:
                error_log.write(error + "\n")

    if os.path.exists(output_pdf):
        return FileResponse(
            path=output_pdf,
            filename=f"{file_name}.pdf",
            media_type="application/pdf",
            background=None
        )
    else:
        raise HTTPException(
            status_code=500, 
            detail="PDF file was not created successfully. Errors: " + "; ".join(errors)
        )


@app.get("/health")
async def health_check():
    """Check if the service is running."""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
