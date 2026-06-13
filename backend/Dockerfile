FROM python:3.12-slim

WORKDIR /app

# 安裝 claude CLI（Claude Code 引擎用，與 ollama 二選一）。
# 裝在映像內 → 架構正確、不依賴主機版本；認證另由 compose 掛載 ~/.claude。
# 失敗（如 build 環境無網路）不影響其餘功能，claude 引擎只會顯示為不可用。
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && (curl -fsSL https://claude.ai/install.sh | bash || echo "claude install skipped")
ENV PATH="/root/.local/bin:${PATH}"

# 先裝依賴（利用快取層）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY . .

# 圖片落地目錄（compose 會掛 volume 到此）
ENV DATA_DIR=/data
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
