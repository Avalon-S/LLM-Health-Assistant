# Use official Python 3.9 image
FROM python:3.9

# Set Workdir
WORKDIR /app

# Copy Project Files
COPY . /app
COPY .env /app/.env

# Install Dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Running the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
