from fastapi import FastAPI, HTTPException
import subprocess
import os
from string import Template
from pydantic import BaseModel
from typing import Literal, Optional
import uvicorn

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


def normalize_path(path: str) -> str:
    """Normalize file paths for Docker environment"""
    path = path.replace(".md", "")

    base_dir = "test"  # Base directory for file operations

    if "/cheatmark/" in path:
        path = path.split("/cheatmark/")[-1]

    path = path.lstrip("/")

    if path.startswith(f"{base_dir}/"):
        path = path[len(f"{base_dir}/") :]

    if not path.startswith(f"{base_dir}/"):
        path = f"{base_dir}/{path}"

    return path


def render_latex(path: str, template_config: TemplateConfig) -> None:
    normalized_path = normalize_path(path)

    if not os.path.exists(f"{normalized_path}.md"):
        raise HTTPException(
            status_code=404, detail=f"Input file not found: {normalized_path}.md"
        )

    pandoc_command = [
        "pandoc",
        "--from=markdown",
        f"--output={normalized_path}.tex",
        f"{normalized_path}.md",
    ]
    result = subprocess.run(
        pandoc_command, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Pandoc error: {result.stderr}")
    create_final_tex(normalized_path, template_config)


def get_template_path(filename: str) -> str:
    print(os.getcwd())
    return os.path.join("./template", filename)
    return os.path.join("/app/template", filename)


def create_final_tex(path: str, template_config: TemplateConfig) -> None:
    with open(f"{path}_temp.tex", "w", encoding="utf-8") as final_tex:
        try:
            header_path = get_template_path("HEADER.txt")
            with open(header_path, "r", encoding="utf-8") as header_file:
                header_template = Template(header_file.read())
                header_data = template_config.model_dump()
                final_tex.write(header_template.substitute(header_data))

            # Read content
            with open(f"{path}.tex", "r", encoding="utf-8") as content_file:
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


def render_pdf(path: str) -> None:
    abs_path = os.path.abspath(path)
    working_dir = os.path.dirname(abs_path)
    base_name = os.path.basename(path)

    pdflatex_command = [
        "pdflatex",
        "-synctex=1",
        "-interaction=nonstopmode",
        "-file-line-error",
        "-output-directory",
        working_dir,
        f"{base_name}_temp.tex",
    ]

    result = subprocess.run(
        pdflatex_command,
        cwd=working_dir,
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
            f"Working Directory: {working_dir}\n"
            f"Input File: {base_name}_temp.tex\n"
            f"Error Details:\n{error_msg}"
        )

        raise HTTPException(status_code=500, detail=full_error)


def clean_up(path: str) -> None:
    try:
        if os.path.exists(f"{path}_temp.pdf"):
            os.rename(f"{path}_temp.pdf", f"{path}.pdf")

        if os.path.exists(f"{path}_temp.tex"):
            os.rename(f"{path}_temp.tex", f"{path}.tex")

        dir_path = os.path.dirname(path)
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

    try:
        normalized_path = normalize_path(request.path)
        template_config = request.template_config or TemplateConfig()
        render_latex(normalized_path, template_config)
        render_pdf(normalized_path)
        clean_up(normalized_path)

        if not os.path.exists(f"{normalized_path}.pdf"):
            raise HTTPException(
                status_code=500, detail="PDF file was not created successfully"
            )

        return ConversionResponse(
            status="success",
            message="PDF conversion completed",
            output_path=f"{normalized_path}.pdf",
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
