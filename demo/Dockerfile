FROM vpanton/docker-tengine-dyups

RUN apt-get install -y  supervisor


#Install pip

RUN wget https://bootstrap.pypa.io/get-pip.py && python get-pip.py

#Install python library for dyups script
RUN pip install requests python-consul

ADD nginx.conf /etc/nginx/nginx.conf
RUN rm -rf /etc/nginx/conf
ADD conf   /etc/nginx/conf

ADD scripts/update_nginx_upstream.py /root/scripts/update_nginx_upstream.py 
ADD  supervisor/supervisord.conf /etc/supervisor/supervisord.conf
ADD supervisor/conf.d /etc/supervisor/conf.d
RUN ls -lR /etc/supervisor

EXPOSE 80 443 8081

CMD /usr/bin/supervisord -c  /etc/supervisor/supervisord.conf
