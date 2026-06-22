FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# El historico SQLite se guarda en /app/data (montar como volumen para persistir)
VOLUME ["/app/data"]
EXPOSE 8765

# Nota: para leer el puerto serie real hay que pasar el dispositivo al contenedor:
#   docker run --device=/dev/ttyUSB0 -p 8765:8765 -v $PWD/data:/app/data apolo27-backend
# En Windows el acceso a COM desde Docker es limitado: para pista, correr el
# backend nativo (python server.py) y dockerizar solo en analisis/replay.
CMD ["python", "server.py", "--sim"]
