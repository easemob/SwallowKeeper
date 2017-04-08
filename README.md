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

## Install and Configure
 
 It's assumed consul cluster has been setup successfully in your environment and services are already registered.

  ```
   1. Build tengine with dyups and install it
   
   2. configure dyups configs in tengine
      
       server {
        listen  127.0.0.1:18882;
        location / {
            dyups_interface; # Define the dyups api interface
        }
       }
      
      Reference: https://github.com/yzprofile/ngx_http_dyups_module
 
   3. Install consul agent on tengine server so that script update_nginx_upstream.py can fetch all services information registered in consul via it.
   
   4. Change variables in scripts/update_nginx_upstream.py 
   
      eg:
         # NGINX_DYUPS_ADDR: Define dyups management url, it's configured on the same host with nginx
         NGINX_DYUPS_ADDR = "http://127.0.0.1:18882"
         
         #UPSTREAM_FILE: Define upstream config file to persist servers information from consul server, this config file will be updated
         # automatically once any service status changes or after LONG_POLLING_INTERVAL time
        UPSTREAM_FILE = "/home/dyups/apps/config/nginx/conf.d/dyups.upstream.com.conf"
        # MIN_CONSUL_SERVICE_NUM: Define a service count threshold in case of any consul server crash, if the live upstream
        # count is less than MIN_CONSUL_SERVICE_NUM, it will not sync the consul services into nginx and nginx will use the old upstreams. We set
        it as 30 in production, you can set it as 0 in demo.
        MIN_CONSUL_SERVICE_NUM = 30
        
        
  5. Run script update_nginx_upstream.py with supervisor


  6. Register service information (ip, port, health check etc) into consul

     Our springboot mirco service implements the service registration in code,
     when the app starts, it will register the service information into consul.

     For test, you can use curl to register, please find the example in below demo.
 
  ```

## Demo

 * __Start consul with web ui__

   docker run --name consul_test -d -p 8400:8400 -p 8500:8500 -p 8600:53/udp -h
   node1 progrium/consul -server -bootstrap -ui-dir /ui

   Note: access http://<ip>:8500/ui to check the services

 *  __Build and Start tengine with dyups and update_nginx_consul script__

   cd demo && docker build -t easemob/swallowkeeper .

   sudo docker run -d --name dyups_consul_test  --link consul_test:consul_test
   -p 80:80 -p 443 -p 8081:8081 easemob/swallowkeeper
  
 * __Register a fake 80 http service to test service__

    curl -X POST 127.0.0.1:8500/v1/agent/service/register -d
    '{"ID":"1234","Name":"test","Tags":["slave"],"Port":80,"check":{"script":
    "echo 0", "interval": "10s"}}'

 * __Check the test upsteam in nginx__

   $ curl localhost:8081/detail

     test

     server 192.168.42.2:80

   The service ip 192.168.42.2 and port 80 is what we registerd with above
   register http api, and you will see it from the output `curl
   localhost:8081/detail. If you register multiple service for test, it will
   show multiple servers under test upstream. 
   
   (Note: upstream name should be same with the service name in consul)`  

   Please feel free to try it.
