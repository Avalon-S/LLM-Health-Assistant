# Select Python 3.9 as the base image
FROM python:3.9.21

# Set Workdir
WORKDIR /app

# Copy Project Files
COPY . /app

# Install Dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Running the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]