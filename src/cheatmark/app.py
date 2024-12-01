from fastapi import FastAPI, HTTPException
import subprocess
import os
from string import Template
from pydantic import BaseModel
from typing import Literal, Optional
import uvicorn

OUTPUT_DIR = "test"

app = FastAPI(
    title="CheatMark", description="Convert markdown files to PDF cheat sheets"
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
    path: str
    template_config: Optional[TemplateConfig] = None


class ConversionResponse(BaseModel):
    status: str
    message: str
    output_path: str
    template_config: dict

def getFileName(path: str) -> str:
    return os.path.basename(path).split(".")[0]

def get_template_path(file_name: str) -> str:
    print(os.getcwd())
    return os.path.join("./template", file_name)
    return os.path.join("/app/template", file_name)

def render_latex(file_name: str, template_config: TemplateConfig) -> None:
    pandoc_command = [
        "pandoc",
        "--from=markdown",
        f"--output={file_name}.tex",
        f"{file_name}.md",
    ]
    result = subprocess.run(
        pandoc_command, capture_output=True, text=True, encoding="utf-8", cwd=OUTPUT_DIR
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Pandoc error: {result.stderr}")
    create_final_tex(file_name, template_config)



def create_final_tex(file_name: str, template_config: TemplateConfig) -> None:
    with open(os.path.join(OUTPUT_DIR, f"{file_name}_temp.tex"), "w", encoding="utf-8") as final_tex:
        try:
            header_path = get_template_path("HEADER.txt")
            with open(header_path, "r", encoding="utf-8") as header_file:
                header_template = Template(header_file.read())
                header_data = template_config.model_dump()
                final_tex.write(header_template.substitute(header_data))

            # Read content
            with open(os.path.join(OUTPUT_DIR, f"{file_name}.tex"), "r", encoding="utf-8") as content_file:
                final_tex.write(content_file.read())

            # Read footer
            footer_path = get_template_path("FOOTER.txt")
            with open(footer_path, "r", encoding="utf-8") as footer_file:
                final_tex.write(footer_file.read())

        except FileNotFoundError as e:
            raise HTTPException(
                status_code=404, detail=f"Template file not found: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"File operation error: {str(e)}"
            )


def render_pdf(file_name: str) -> None:

    pdflatex_command = [
        "pdflatex",
        "-synctex=1",
        "-interaction=nonstopmode",
        "-file-line-error",
        f"{file_name}_temp.tex",
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
            f"Input File: {file_name}_temp.tex\n"
            f"Error Details:\n{error_msg}"
        )

        raise HTTPException(status_code=500, detail=full_error)


def clean_up(path: str) -> None:
    try:
        full_path = os.path.join(OUTPUT_DIR, path)
        if os.path.exists(f"{full_path}_temp.pdf"):
            os.rename(f"{full_path}_temp.pdf", f"{full_path}.pdf")

        if os.path.exists(f"{full_path}_temp.tex"):
            os.rename(f"{full_path}_temp.tex", f"{full_path}.tex")

        dir_path = os.path.dirname(full_path)
        base_name = os.path.basename(path)
        for file in os.listdir(dir_path):
            if file.startswith(f"{base_name}_temp") and file.endswith(
                (".aux", ".log", ".out", ".synctex.gz")
            ):
                os.remove(os.path.join(dir_path, file))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup error: {str(e)}")


@app.post("/convert", response_model=ConversionResponse)
async def convert_to_pdf(request: ConversionRequest):
    if not request.path:
        raise HTTPException(status_code=400, detail="Path cannot be empty")
    file_name = getFileName(request.path)   

    try:
        template_config = request.template_config or TemplateConfig()
        try:
            render_latex(file_name, template_config)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error rendering LaTeX: {str(e)}")

        try:
            render_pdf(file_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error rendering PDF: {str(e)}")

        try:
            clean_up(file_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error during cleanup: {str(e)}")

        if not os.path.exists(f"{file_name}.pdf"):
            raise HTTPException(
                status_code=500, detail="PDF file was not created successfully"
            )

        return ConversionResponse(
            status="success",
            message="PDF conversion completed",
            output_path=f"{file_name}.pdf",
            template_config=template_config.model_dump(),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Conversion error: {str(e)}")


@app.get("/health")
async def health_check():
    """Check if the service is running."""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
