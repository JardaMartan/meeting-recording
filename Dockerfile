FROM python:3.9

LABEL maintainer="@jardamartan"

WORKDIR /code

# copy the dependencies file to the working directory
COPY requirements.txt .

# proxies for the pip install
#ENV http_proxy http://proxy_host:port
#ENV https_proxy http://proxy_host:port

# install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY .env_docker .env

# copy the content of the local src directory to the working directory
COPY src/ .

# command to run on container start
CMD [ "recording_bot.py", "-vv" ]
