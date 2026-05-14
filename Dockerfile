FROM node:20-slim

WORKDIR /app

# Install system dependencies
# poppler-utils (pdftotext) للاستخراج الأساسي
# Python + PyMuPDF للتحويل المتقدم (اختياري)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      poppler-utils \
      libreoffice-writer \
      libreoffice-java-common \
      python3 \
      python3-pip \
      && \
    rm -rf /var/lib/apt/lists/*

# Install PyMuPDF للـ RSWS Python converter المتقدم (اختياري)
RUN pip3 install PyMuPDF==1.24.9 python-docx==1.1.2 --break-system-packages 2>/dev/null || true

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

RUN mkdir -p uploads

EXPOSE 3000

CMD ["node", "src/index.js"]
