# Use Ubuntu as base image
FROM ubuntu:22.04

# Avoid timezone prompt during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install TeX Live, Pandoc and other necessary packages
RUN apt-get update && apt-get install -y \
    texlive-full \
    texlive-lang-german \
    texlive-fonts-extra \
    texlive-fonts-recommended \
    texlive-font-utils \
    texlive-latex-extra \
    texlive-xetex \
    pandoc \
    make \
    git \
    wget \
    python3 \
    python3-pip \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install mermaid-filter
RUN npm install -g mermaid-filter

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml requirements.txt ./
COPY src/ ./src/
COPY template/ ./template/
COPY test/ ./test/

# Install Python dependencies
RUN pip3 install -r requirements.txt
RUN pip3 install .

# Create test directory if it doesn't exist
RUN mkdir -p /app/test && \
    mkdir -p /data && \
    chmod -R 777 /app/test && \
    chmod -R 777 /data

# Create a volume for data persistence
VOLUME ["/data"]

# Expose the FastAPI port
EXPOSE 8000

# Command to run the FastAPI application
CMD ["python3", "-m", "cheatmark.app"] 