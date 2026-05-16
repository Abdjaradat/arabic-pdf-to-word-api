FROM node:20-slim

WORKDIR /app

# Install system dependencies
# poppler-utils (pdftotext) للاستخراج الأساسي
# tesseract-ocr للتعرف على النص في الصور
# Python + PyMuPDF للتحويل المتقدم
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      poppler-utils \
      libreoffice-writer \
      libreoffice-java-common \
      python3 \
      python3-pip \
      tesseract-ocr \
      tesseract-ocr-ara \
      tesseract-ocr-script-arab \
      && \
    rm -rf /var/lib/apt/lists/*

# Install Python libraries للاستخراج متعدد الطرق + OCR
RUN pip3 install PyMuPDF==1.24.9 python-docx==1.1.2 --break-system-packages 2>/dev/null || true
RUN pip3 install pdf2image pytesseract pdfplumber pypdf --break-system-packages 2>/dev/null || true

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

RUN mkdir -p uploads

EXPOSE 3000

CMD ["node", "src/index.js"]
