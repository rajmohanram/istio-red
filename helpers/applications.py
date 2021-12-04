import yaml
import logging
from .kialiApi import call_kiali_api
from pprint import pprint
from addict import Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(message)s")


# Get Istio enabled namespaces
def get_istio_namespaces(host):
    endpoint = "/namespaces"
    ns_list = list()
    response = call_kiali_api(host, endpoint)
    for item in response:
        try:
            if item['labels']['istio-injection'] == "enabled":
                ns_list.append(item['name'])
        except (KeyError, TypeError):
            pass
    return ns_list


# Get applications enabled with istio
def get_istio_applications(istio_url):
    host = istio_url

    # get istio enabled namespaces
    namespaces_list = get_istio_namespaces(host)

    # dict to output to YAML file
    namespaces_apps = {}

    # get apps in the namespace
    ns_app_list = list()
    for ns in namespaces_list:
        endpoint = "/namespaces/" + ns + "/apps"
        app_dict = dict()
        app_dict['name'] = ns
        apps_list = list()
        response = call_kiali_api(host, endpoint)
        applications_list = response['applications']
        for app in applications_list:
            apps_list.append(app['name'])
        app_dict['apps'] = apps_list
        ns_app_list.append(app_dict)
    namespaces_apps['namespaces'] = ns_app_list

    # write out istio_apps YAML file
    with open('istio_apps.yaml', 'w') as f:
        document = yaml.dump(namespaces_apps, f)


# get app health
def get_app_health(host, ns, app):
    endpoint = "/namespaces/" + ns + "/apps/" + app + "/health"
    response = call_kiali_api(host, endpoint)
    workload_statuses = response['workloadStatuses']
    inbound_requests = dict()
    outbound_requests = dict()

    # check for http key
    try:
        inbound_requests = response['requests']['inbound']['http']
        outbound_requests = response['requests']['outbound']['http']
    except KeyError:
        pass
    return workload_statuses, inbound_requests, outbound_requests


# check app health
def check_app_health(host, ns, app):
    app_health = "healthy"
    app_health_reason = ""
    workload_statuses, inbound_requests, outbound_requests = get_app_health(host, ns, app)

    # check workload status
    for workload in workload_statuses:
        desired_replicas = workload['desiredReplicas']
        current_replicas = workload['currentReplicas']
        available_replicas = workload['availableReplicas']
        synced_proxies = workload['syncedProxies']
        if not desired_replicas == current_replicas == available_replicas == synced_proxies:
            app_health = "unhealthy"
            app_health_reason = "Workload Issue"

    # check inbound http status code
    for key in inbound_requests.keys():
        if key.startswith(('3', '4', '5')):
            app_health = "unhealthy"
            app_health_reason = "HTTP Request Issue (Inbound)"

    # check outbound http status code
    for key in outbound_requests.keys():
        if key.startswith(('3', '4', '5')):
            app_health = "unhealthy"
            app_health_reason = "HTTP Request Issue (Outbound)"

    return app_health, app_health_reason


# get app health
def app_health(istio_url):
    host = istio_url
    logging.info("Reading istio_apps.yaml file")
    with open('istio_apps.yaml', 'r') as f:
        apps_dict = yaml.load(f, Loader=yaml.FullLoader)
        apps_list = apps_dict['namespaces']

    # app_health_yaml
    app_health_yaml = dict()
    healthy_apps = list()
    unhealthy_apps = list()
    unknown_apps = list()

    logging.info("Checking application health")
    # check health of each app per namespace
    for applications in apps_list:
        namespace = applications['name']
        app_list = applications['apps']
        for app in app_list:
            app_health, reason = check_app_health(host, namespace, app)
            if app_health == "healthy":
                tmp_dict = {"namespace": namespace, "app": app}
                healthy_apps.append(tmp_dict)
            else:
                tmp_dict = {"namespace": namespace, "app": app, "reason": reason}
                unhealthy_apps.append(tmp_dict)

    # load app health dict for yaml out
    app_health_yaml['healthy'] = healthy_apps
    app_health_yaml['unhealthy'] = unhealthy_apps
    app_health_yaml['unknown'] = unknown_apps

    # write out app health YAML file
    with open('app_health.yaml', 'w') as f:
        document = yaml.dump(app_health_yaml, f)
    logging.info("Updated application health YAML file")


# get app health details
def get_app_health_details(host, ns, app):
    workload_statuses, inbound_requests, outbound_requests = get_app_health(host, ns, app)
    # workload status
    wkld_statuses = list()
    for item in workload_statuses:
        tmp_list = [item['name'], item['desiredReplicas'], item['currentReplicas'], item['availableReplicas'],
                    item['syncedProxies']]
        wkld_statuses.append(tmp_list)
    # http status code statistics
    http_status_code_stats = list()
    # inbound requests
    in_rps_list_2xx = round(sum([v for k, v in inbound_requests.items() if k.startswith('2')]), 2)
    in_rps_list_3xx = round(sum([v for k, v in inbound_requests.items() if k.startswith('3')]), 2)
    in_rps_list_4xx = round(sum([v for k, v in inbound_requests.items() if k.startswith('4')]), 2)
    in_rps_list_5xx = round(sum([v for k, v in inbound_requests.items() if k.startswith('5')]), 2)
    http_status_code_stats.append(['Inbound', in_rps_list_2xx, in_rps_list_3xx, in_rps_list_4xx, in_rps_list_5xx])
    # outbound requests
    out_rps_list_2xx = round(sum([v for k, v in outbound_requests.items() if k.startswith('2')]), 2)
    out_rps_list_3xx = round(sum([v for k, v in outbound_requests.items() if k.startswith('3')]), 2)
    out_rps_list_4xx = round(sum([v for k, v in outbound_requests.items() if k.startswith('4')]), 2)
    out_rps_list_5xx = round(sum([v for k, v in outbound_requests.items() if k.startswith('5')]), 2)
    http_status_code_stats.append(['Outbound', out_rps_list_2xx, out_rps_list_3xx, out_rps_list_4xx, out_rps_list_5xx])
    return wkld_statuses, http_status_code_stats


# Check app RED
def check_app_red(host, ns, app):
    endpoint = "/namespaces/" + ns + "/applications/" + app + "/graph?graphType=app"
    response = call_kiali_api(host, endpoint)

    # find app id in nodes
    app_id = ''
    for node in response['elements']['nodes']:
        if node['data']['app'] == app:
            app_id = node['data']['id']

    # find stats in edges with matching app id
    request_rate = response_duration = error_percent = 0
    for node in response['elements']['edges']:
        if node['data']['target'] == app_id:
            request_rate = node['data']['traffic']['rates']['http']
            response_duration = node['data']['responseTime']
            try:
                error_percent = node['data']['traffic']['rates']['httpPercentErr']
            except (KeyError, TypeError):
                pass
    logging.info("Collected RED for App")
    return float(request_rate), float(error_percent), float(response_duration)


# get app RED
def app_red(istio_url, resp_duration_threshold):
    host = istio_url
    duration_threshold = resp_duration_threshold
    logging.info("Reading istio_apps.yaml file")
    with open('istio_apps.yaml', 'r') as f:
        apps_dict = yaml.load(f, Loader=yaml.FullLoader)
        apps_list = apps_dict['namespaces']

    # app_red_yaml
    app_red_yaml = dict()
    app_rate_list = list()
    app_error_list = list()
    app_duration_list = list()

    logging.info("Start of RED stats collection")
    # check graph for each app per namespace
    for applications in apps_list:
        namespace = applications['name']
        app_list = applications['apps']
        for app in app_list:
            rate, error, duration = check_app_red(host, namespace, app)
            if rate == 0:
                tmp_rate_list = {'app': app, 'rate': rate}
                app_rate_list.append(tmp_rate_list)
            if error != 0:
                tmp_error_list = {'app': app, 'error': error}
                app_error_list.append(tmp_error_list)
            if duration > duration_threshold:
                tmp_duration_list = {'app': app, 'duration': duration}
                app_duration_list.append(tmp_duration_list)
    # load app red dict for yaml out
    app_red_yaml['rate'] = app_rate_list
    app_red_yaml['error'] = app_error_list
    app_red_yaml['duration'] = app_duration_list

    # write out app red YAML file
    with open('app_red.yaml', 'w') as f:
        document = yaml.dump(app_red_yaml, f)
    logging.info("Updated application RED YAML file")