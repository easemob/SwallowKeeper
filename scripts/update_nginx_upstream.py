#!/usr/bin/env python
# -*- coding: utf-8 -*-
import consul
import logging
import requests
import time

# Initialize consul client
c = consul.Consul()

# service_exclude: Define services that are not needed to sync to nginx upstream
service_exclude = ['consul']

# LONG_POLLING_INTERVAL: the maximum duration to wait (e.g. ‘10s’) to retrieve a given index. this parameter is only applied if index is
# also specified. the wait time by default is 5 minutes.
LONG_POLLING_INTERVAL = '180s'

# NGINX_DYUPS_ADDR: Define dyups management url, it's configured on the same host with nginx
NGINX_DYUPS_ADDR = "http://127.0.0.1:18882"

# NGINX_UPSTREAM_PREFIX: Define dyups upstream api url to retrieve all upstream information
NGINX_UPSTREAM_PREFIX = NGINX_DYUPS_ADDR + '/' + 'upstream/'

# NGINX_UPSTREAM_DETAIL: Define dyups upstream details information to retrieve server information about specific upstream
NGINX_UPSTREAM_DETAIL = NGINX_DYUPS_ADDR + '/' + 'detail'

# UPSTREAM_FILE: Define upstream config file to persist servers information from consul server, this config file will be updated
# automatically once any service status changes or after LONG_POLLING_INTERVAL time
UPSTREAM_FILE = "/home/dyups/apps/config/nginx/conf.d/dyups.upstream.com.conf"

# KEEPALIVE_CONN_NUM: Define keepalive value for synced service in UPSTREAM_FILE
KEEPALIVE_CONN_NUM = "20"

# UPSTREAM_MAX_FAIL: Define upstream server max_fail property in UPSTREAM_FILE
UPSTREAM_MAX_FAIL = "3"

# UPSTREAM_FAIL_TIMEOUT Define upstream server fail timeout in UPSTREAM_FILE
UPSTREAM_FAIL_TIMEOUT = "2s"

# KEEPALIVE: Define keepalive format in UPSTREAM_FILE
KEEPALIVE = "    keepalive " + KEEPALIVE_CONN_NUM + ";"

# SLEEP_INTERVAL: Define a sleep time in seconds to control the frequency of watching consul server, this will protect consul server
# and reduce consul server load especially when internal error occurs in consul server
SLEEP_INTERVAL = 2

# MIN_CONSUL_SERVICE_NUM: Define a service count threshold in case of any consul server crash, if the live upstream
# count is less than MIN_CONSUL_SERVICE_NUM, it will not sync the consul services into nginx and nginx will use the old
# upstreams
MIN_CONSUL_SERVICE_NUM = 30

# Define log format of this script, we use supervior to manage this script and control the max backups and file size
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p')


class DictDiffer(object):
    """
    Calculate the difference between two dictionaries as:
    (1) items added
    (2) items removed
    (3) keys same in both but changed values
    (4) keys same in both and unchanged values
    """
    def __init__(self, current_dict, past_dict):
        self.current_dict, self.past_dict = current_dict, past_dict
        self.set_current, self.set_past = set(current_dict.keys()), set(past_dict.keys())
        self.intersect = self.set_current.intersection(self.set_past)

    def added(self):
        return self.set_current - self.intersect

    def removed(self):
        return self.set_past - self.intersect

    def changed(self):
        return set(o for o in self.intersect if self.past_dict[o] != self.current_dict[o])

    def unchanged(self):
        return set(o for o in self.intersect if self.past_dict[o] == self.current_dict[o])

    def getChanges(self):
        updates = {}
        updates["added_items"] = list(self.added())
        updates["removed_items"] = list(self.removed())
        updates["changed_items"] = list(self.changed())
        return updates


def getConsulServices(index):
    (index, services_tags) = c.catalog.services(index=index, wait=LONG_POLLING_INTERVAL)
    services_names = services_tags.keys()
    services_names = list(set(services_names).difference(set(service_exclude)))
    service_upstream = {}
    for service_name in services_names:
        (index_health, service_nodes) = c.health.service(service_name)
        if service_nodes:
            for service in service_nodes:
                service_id = service['Service']['ID']
                service_ip = service['Node']['Address']
                service_port = str(service['Service']['Port'])
                server_addr = service_ip + ":" + service_port
                # service_check list is used to get the corresponding unique service check for the specific service as one service may have many checks.
                #  eg: WebappReadwrite has 2 checks, one is selfhealth, the other is WebappReadwrite (which is what we
                # need to check). If the service check list donesn't contain the corresponding service check, then this instance will not sync to nginx upstream.
                service_check = [service_check for service_check in service['Checks'] if service_id in service_check.values()]
                if service_check:
                    service_status = service_check[0]['Status']
                    gray_tags = [tmp for tmp in service['Service']['Tags'] if 'gray=' in tmp]
                    gray_tag = gray_tags and gray_tags[0].split('=')[1]
                    if not gray_tag or gray_tag == "default":
                        upstream_name = service_name
                        if upstream_name not in service_upstream:
                            service_upstream[upstream_name] = []
                    else:
                        upstream_name = service_name + "_" + str(gray_tag)
                        if upstream_name not in service_upstream:
                            service_upstream[upstream_name] = []

                    if service_status == 'passing':
                        logging.info("%s server %s status is passing, this server will updated into nginx upstream." % (upstream_name, server_addr))
                        service_upstream[upstream_name].append(server_addr)
                    else:
                        logging.warning(" %s server %s status is %s , this server will not be updated into nginx upstream" % (upstream_name, server_addr, service_status))
                else:
                    logging.error("%s instance %s does't have health check defined." % (service_name, server_addr))

    return (index, service_upstream)


def updateNginxUpstream(consul_services_old, consul_services):
    differ = DictDiffer(consul_services, consul_services_old)
    differChanges = {}
    # differChanges exmaple: {'added_items': ['A','B'], 'changed_itmes': ['C'], 'removed_items': ['D']}
    # Service A,B  are new registed in consul and need to add upstream A,B in nginx. Service C has some changes, it might add more servers or reduce servers. Service D is
    # deregisted from consul, it might no longer used, so need to delete upstream D in nginx
    differChanges = differ.getChanges()
    removed_services = differChanges['removed_items']
    if len(removed_services) > 0:
        persistUpstreams(consul_services)
        for removed_service in removed_services:
            logging.info("Begin to remove upstream %s it's not in consul now!" % removed_service)
            status_code = delNginxUpstream(removed_service)
            if status_code == 200:
                logging.info("Remove upstream %s successfully!" % removed_service)
            else:
                logging.warning("Failed to remove upstream %s" % removed_service)

    added_services = differChanges['added_items']
    if len(added_services) > 0:
        persistUpstreams(consul_services)
        for added_service in added_services:
            added_servers = consul_services.get(added_service)
            upstream_servers = ""
            for added_server in added_servers:
                upstream_server = "server " + added_server + ";"
                upstream_servers = upstream_servers + upstream_server

            addNginxUpstreamServer(added_service, upstream_servers)

    changed_services = differChanges['changed_items']
    if len(changed_services) > 0:
        persistUpstreams(consul_services)
        for changed_service in changed_services:
            logging.info("service %s upstream servers has changed." % changed_service)
            changed_servers = consul_services.get(changed_service)
            upstream_servers = ""
            for changed_server in changed_servers:
                upstream_server = "server " + changed_server + ";"
                upstream_servers = upstream_servers + upstream_server

            addNginxUpstreamServer(changed_service, upstream_servers)


def addNginxUpstreamServer(serviceName, upstreamServers):
    upstream_url = NGINX_UPSTREAM_PREFIX + serviceName
    res = None
    try:
        res = requests.post(upstream_url, data=upstreamServers)
    except requests.exceptions.ConnectionError:
        logging.error("Can't not connect to local nginx dyups management interface when adding upstream %s server %s  please check it,  will exit program now." % (serviceName, upstreamServers))
        return
    except requests.exceptions.RequestException as e:
        logging.error("Request error occured when adding upstream %s server %s , will exit program." % (serviceName, upstreamServers))
        logging.error(e)
    if res:
        if res.status_code == 200:
            logging.info("Add server %s into upstream %s Successfully!" % (upstreamServers, serviceName))
        else:
            logging.error("Failed to add server %s into upstream %s" % (upstreamServers, serviceName))
    else:
        return None


def removeNginxUpstreamServer(upstream, serverAddr):
    """  eg:  serverAddr:120.10.10.10:8555"""
    pass


def delNginxUpstream(serviceName):
    """ Delete upstream: eg WebappReadwrite_b """

    upstream_url = NGINX_UPSTREAM_PREFIX + serviceName
    res = None
    try:
        res = requests.delete(upstream_url)
    except requests.exceptions.ConnectionError:
        logging.error("Can't not connect to local nginx dyups management interface when deleting upstream server %s  please check it,  will exit program now." % (upstream_url))
        return
    except requests.exceptions.RequestException as e:
        logging.error("Request error occured when deleting upstream %s , will exit program." % upstream_url)
        logging.error(e)
        return
    if res:
        return res.status_code
    else:
        return None


def persistUpstreams(consul_services):
    """ Persist consul service changes into nginx upstream configuration files in case of losing data when reloading."""
    logging.info("Persisting consul service changes into upstream configs")
    logging.info("persit consul services ", consul_services)
    try:
        with open(UPSTREAM_FILE, 'w') as f:
            for service in consul_services:
                if len(consul_services[service]) > 0:
                    upstream = "upstream " + service + " {"
                    f.write(upstream + '\n')
                    for server in consul_services[service]:
                        upstream_server = "    server " + server + " max_fails=%s" % UPSTREAM_MAX_FAIL + " fail_timeout=%s" % UPSTREAM_FAIL_TIMEOUT + ";"
                        f.write(upstream_server + '\n')
                    f.write(KEEPALIVE + '\n')
                    f.write("}" + '\n')
                    f.write('\n')
    except IOError:
        logging.error("IOError when persisting to config file %s" % UPSTREAM_FILE)
        return
    except Exception:
        logging.error("Error during persiting upstream servers into %s" % UPSTREAM_FILE)
        return
    logging.info("Persisting configs finished!")


def main():

    index_old = None
    consul_services_old = {}

    while True:

        time.sleep(SLEEP_INTERVAL)

        try:
            (index, consul_services) = getConsulServices(index_old)
            #check consul service count to ensure the services are really up running, in case consul was in incorrect and
            # return empty service list and cause nginx upstreams deleted unexpectedly.
            if consul_services and len(consul_services) < MIN_CONSUL_SERVICE_NUM:
                    logging.error("Consul service number is less than %d , please check the system!" % MIN_CONSUL_SERVICE_NUM)
                    continue
        except requests.exceptions.ConnectionError:
            logging.error("Can't not connect to local consul agent, please check it,  will exit program.")
            continue
        except requests.exceptions.RequestException as err:
            logging.error("There is http request error during calling consul agent, will exit program")
            logging.error(err)
            continue
        except Exception as err:
            logging.error(err)
            continue

        logging.info("There are %d service found in consul." % len(consul_services))

        if index_old is None:
            index_old = 'empty'
        logging.info("---new index is " + index + " old index is " + index_old)

        if index != index_old:
            updateNginxUpstream(consul_services_old, consul_services)
            logging.info("old consul services" + str(consul_services_old))
            logging.info("-----------")
            logging.info("new consul services" + str(consul_services))
            index_old = index
            consul_services_old = consul_services
        else:
            logging.info("Nothing changes")

if __name__ == "__main__":
    main()
