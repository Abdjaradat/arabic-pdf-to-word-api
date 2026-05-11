FROM node:20-slim

WORKDIR /app

# Install LibreOffice for layout-preserving PDF→DOCX conversion
# + poppler-utils (pdftotext) for Arabic text extraction
# + Tesseract OCR with Arabic for AI text verification
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      libreoffice-writer \
      libreoffice-java-common \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-ara \
      && \
    rm -rf /var/lib/apt/lists/*

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

RUN mkdir -p uploads

EXPOSE 3000

CMD ["node", "src/index.js"]
