# SwallowKeeper
###
Easemob/SwallowKeeper is a simple and handy autoscale solution for micro service, it is composed of nginx (tengine), dyups and consul, it updates the upstream list by watching consul services, once any serivce changes found or timeouts, it will persistent the updated upstreams first in case of consul server crash and then update upstreams into memory, which will take effect in near real time without reloading nginx. SwallowKeeper can reduce much operation time by automating removing/adding upstream servers without reloading nginx when deploying app or restarting app for a configuration change. In our customer service project, all springboot micro services apply this solution, each springboot app auto registers itself into consul when starting, and deregisters itself when stopping. Honestly, this make our operation team's life much more easier.

This solution can apply to not just java language, also apply to python, ruby, php etc. The consul role in this solution can be replaced with etcd/zookeeper as well, this will be repleased in future.
###
## Advantage

 * __Users will not be aware of any breaks during upstream service restarts or service crash.__
 Without this solution, if any service crashes  all of a sudden, nginx will only be aware of this after retry_times * check interval, users will get 502 response durint this period. With consul watch mechanism, nginx can notice the service status change in near real time, and users will not aware of the service break.

* __This solution is not intrusive for application codes.__
  Application codes doesn't need to change, what is needed is only few nginx dyups module configs and a script for watching consul changes.

* __Nginx dyups module provides restful api to manage upstream servers, it's easy to implement our own tool to manage upsstream servers.__

## Architecture in our environment

  ![Kefu autoscale structure](https://github.com/easemob/SwallowKeeper/blob/master/images/dyups_consul_app.png)
  
  
## Components
 * __tengine with dyups module__
 
   We built tengine 2.1.2 with dyups, and it has been running ok in production for 1 year.
 * __consul cluster__
 
    __Consul Client__: We deploy consul client on each host, all micro services on that host will register their information into local consul agent (including service information, health check etc). Then Consul agent sync these information to consul servers.
    
   __Consul Server__: It's recommended to use 3 or 5 nodes to form the consul server cluster to guarantee high avalibility. Clients can get all registered services information via consul servers.
    
    
 * __update_nginx_upstream.py__
 
   One script reads upstreams information from consul server and updates them into tengine memory with dyups api, and this will take effect in near real time without reloading tengine.

### Build tengine rpm package with dyups and luajit module
 (dyups is to support autoscale and luajit is to support blue/green deployment)
 
 * Install dependence
   ```
     sudo yum install -y pcre-devel GeoIP-devel openssl openssl-devel pcre
   ```
 * Configure tengine 2.1.2 installation environment 
   After downloading tengine 2.1.2 source code, run

   ```
     ./configure --with-http_geoip_module --with-http_lua_module  --with-syslog
     --with-http_ssl_module --with-http_realip_module
     --with-http_addition_module --with-http_sub_module --with-http_dav_module
     --with-http_flv_module --with-http_mp4_module --with-http_gunzip_module
     --with-http_gzip_static_module --with-http_random_index_module
     --with-http_secure_link_module --with-http_stub_status_module
     --with-file-aio --with-cc-opt='-O2 -g -pipe -Wp,-D_FORTIFY_SOURCE=2
     -fexceptions -fstack-protector --param=ssp-buffer-size=4 -m64
     -mtune=generic' --without-mail_pop3_module --without-mail_imap_module
     --without-mail_smtp_module --prefix=/home/dyups/apps/opt/nginx
     --conf-path=/home/dyups/apps/config/nginx/nginx.conf --user=dyups
     --group=dyups --pid-path=/home/dyups/apps/var/nginx/nginx.pid
     --error-log-path=/home/dyups/apps/log/nginx/error.log
     --http-log-path=/home/dyups/apps/log/nginx/access.log
     --sbin-path=/home/dyups/apps/opt/nginx/sbin/nginx
     --lock-path=/home/dyups/apps/var/nginx/nginx.lock
     --http-client-body-temp-path=/home/dyups/apps/var/nginx/client_temp
     --http-proxy-temp-path=/home/dyups/apps/var/nginx/proxy_temp
     --http-fastcgi-temp-path=/home/dyups/apps/var/nginx/fastcgi_temp
     --http-uwsgi-temp-path=/home/dyups/apps/var/nginx/uwsgi_temp
     --http-scgi-temp-path=/home/dyups/apps/var/nginx/scgi_temp
     --with-http_dyups_module --with-http_dyups_lua_api --with-http_lua_module
   ```
 * Install tengine
   ```
    make && sudo make install DESTDIR=/tmp/tegine_install  
   ```
 * Use fpm build tengine rpm

  ```
     fpm -s dir -f -t rpm -n tengine  --epoch 0 -v '2.1.2' --verbose \
    -d 'luajit' \
    -d 'libpng-devel' \
    -d 'pcre' \
    -d 'pcre-devel' \
    -d 'openssl' \
    -d 'openssl-devel' \
    -d 'GeoIP-devel' \
    -d 'pcre-devel' \
    --description 'tengine 2.1.2 compiled with dyups' --url 'www.dyups.com' --license 'BSD' \
    --after-install /home/dyups/apps/opt/nginx/link_luajit_so.sh \
    -C /tmp/tegine_install . 
  ``` 
  
  ```
  link_luajit_so.sh, this script is used to configure the lugjit environment, if blue/green deployment is not used, the option "--after-install" can be removed.
  link_luajit_so.sh content:
		echo 'export LUAJIT_LIB=/usr/local/lib/' >>/etc/profile;
		echo 'export LUAJIT_INC=/usr/local/include/luajit-2.0' >>/etc/profile;
		source /etc/profile;
		ln -s /usr/local/lib/libluajit-5.1.so.2 /lib64/libluajit-5.1.so.2;
  ```
  * Install tengine-2.1.2 rpm gengerated by fpm

  ```
    yum install -y tengine-2.1.2.rpm

  ```

###   Change tengine config files about dyups module, refer to the example indyups_config folder

  ```
    server {
        listen  127.0.0.1:18882;
        location / {
            dyups_interface; # Define the dyups api interface
        }
    }
  ```

### After reloading dyups config change in tengine, copy scripts/update_nginx_upstream.py to tengine server and use supervisor to manage this script. 
   This will sync the consul services and persist them into conf.d/dyups.consul.upstream.conf.
