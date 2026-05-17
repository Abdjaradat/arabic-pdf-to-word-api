FROM node:20-slim

WORKDIR /app

# Install system dependencies
# poppler-utils (pdftotext) للاستخراج الأساسي
# tesseract-ocr للتعرف على النص في الصور
# Python + PyMuPDF للتحويل المتقدم
# Install system deps (tesseract-ocr-ara added later via non-free repo)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      poppler-utils \
      libreoffice-writer \
      libreoffice-java-common \
      python3 \
      python3-pip \
      tesseract-ocr \
      && \
    rm -rf /var/lib/apt/lists/*

# Install Python libraries (allow failure — PDF backends optional)
ENV PIP_REQUIRE_VIRTUALENV=0
RUN python3 -m pip install PyMuPDF==1.24.9 python-docx==1.1.2 2>&1 || echo 'WARN: PyMuPDF install failed (non-fatal)'
RUN python3 -m pip install pdf2image pytesseract pdfplumber pypdf 2>&1 || echo 'WARN: extra PDF backends failed (non-fatal)'

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

RUN mkdir -p uploads

EXPOSE 3000

CMD ["node", "src/index.js"]
