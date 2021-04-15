FROM python:3.8-slim-buster
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir discord.py python-dotenv asyncio
# RUN python3 -m pip install -U discord.py python-dotenv asyncio
# RUN pip3 install -r dotenv
COPY . .
CMD ["python3", "SuperLobbyBot.py"]