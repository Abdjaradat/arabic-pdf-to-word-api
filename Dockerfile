FROM node:20-slim

WORKDIR /app

# Install Python3 for enhanced PDF conversion
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv

COPY requirements.txt ./
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Create symlink so 'python3 convert_pdf.py' uses the venv
RUN ln -sf /opt/venv/bin/python3 /usr/local/bin/python3

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

RUN mkdir -p uploads

EXPOSE 3000

CMD ["node", "src/index.js"]
