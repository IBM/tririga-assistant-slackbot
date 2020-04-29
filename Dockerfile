FROM ubuntu:20.04

LABEL MAINTANER="Jordan Moore <jtmoore@us.ibm.com>"

RUN apt-get update \
  && apt-get install -y python3-pip python3-dev \
  && cd /usr/local/bin \
  && ln -s /usr/bin/python3 python \
  && pip3 install --upgrade pip

#  && pip3 install Flask \
#  && pip3 install ibm_watson \
#  && pip3 install python-dotenv \
#  && pip3 install requests

# Copy just the requirements.txt first to leverage Docker cache
COPY ./requirements.txt /app/requirements.txt

WORKDIR /app

RUN pip3 install -r requirements.txt

COPY . /app

ENTRYPOINT ["python3"]

EXPOSE 8080

CMD [ "app.py" ]