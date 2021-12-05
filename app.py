import yaml
from flask import Flask, render_template, request, jsonify
from flask_apscheduler import APScheduler
from helpers.applications import get_istio_applications, app_health, get_app_health_details, app_red
import os


# set configuration values
class Config:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = "Asia/Kolkata"


# Flask configurations
kiali_url = os.environ.get('KIALI_URL', default='http://kiali.dev.io')
kiali_ext_url = os.environ.get('KIALI_EXT_URL', default='http://kiali.dev.io')
response_duration_threshold = os.environ.get('RESP_DURATION_THRESHOLD', default=10)
scan_interval = os.environ.get('SCAN_INTERVAL', default=20)
app = Flask(__name__)
app.config.from_object(Config())


# initialize scheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()


# Read YAML file
def read_yaml(filename):
    try:
        with open(filename, 'r') as f:
            obj = yaml.load(f, Loader=yaml.FullLoader)
        return obj
    except FileNotFoundError:
        return None


# get istio enables apps - scheduled instance
@scheduler.task('interval', id='do_find_istio_apps', seconds=scan_interval)
def find_istio_apps():
    get_istio_applications(kiali_url)


# check app health
@scheduler.task('interval', id='do_app_health', seconds=scan_interval)
def find_app_health():
    if read_yaml('istio_apps.yaml'):
        app_health(kiali_url)


# check red
@scheduler.task('interval', id='do_app_red', seconds=scan_interval)
def find_app_red():
    if read_yaml('istio_apps.yaml'):
        app_red(kiali_url, response_duration_threshold)


# index page
@app.route("/")
def index():
    # check for app object
    app_obj = read_yaml('istio_apps.yaml')
    if not app_obj:
        return "Server initializing..., please wait for application stats be available"
    else:
        # stats for app health
        app_count = list()
        issues_count = list()
        red_count = list()
        unhealthy_app_list = list()

        # app health summary and app health issues summary
        app_health_obj = read_yaml('app_health.yaml')
        if app_health_obj:
            # app health category count
            healthy_app_count = len(app_health_obj['healthy'])
            unhealthy_app_count = len(app_health_obj['unhealthy'])
            unknown_app_count = len(app_health_obj['unknown'])
            app_count = [healthy_app_count, unhealthy_app_count, unknown_app_count]
            # app health issue category count
            workload_issue = http_issue = 0
            for item in app_health_obj['unhealthy']:
                tmp_list = [item['namespace'], item['app'], item['reason']]
                unhealthy_app_list.append(tmp_list)
                if item['reason'] == "Workload Issue":
                    workload_issue = workload_issue + 1
                if item['reason'].find("HTTP Request Issue") == 0:
                    http_issue = http_issue + 1
            issues_count = [http_issue, workload_issue]

        # app red summary
        app_red_obj = read_yaml('app_red.yaml')
        if app_red_obj:
            red_rate_count = len(app_red_obj['rate'])
            red_error_count = len(app_red_obj['error'])
            red_duration_count = len(app_red_obj['duration'])
            red_count = [red_rate_count, red_error_count, red_duration_count]

        return render_template("index.html", kiali_ext_url=kiali_ext_url,  app_count=app_count,
                               issues_count=issues_count, red_count=red_count,
                               unhealthy_app_list=unhealthy_app_list)


# Get NS list
def get_ns_list():
    app_list_obj = read_yaml('istio_apps.yaml')
    # collect namespaces
    ns_list = list()
    for item in app_list_obj['namespaces']:
        ns_list.append(item['name'])

    return ns_list


# Get App list
def get_app_list(namespace):
    app_list_obj = read_yaml('istio_apps.yaml')
    # collect app names
    app_list = list()
    for item in app_list_obj['namespaces']:
        if item['name'] == namespace:
            for app in item['apps']:
                app_list.append(app)

    return app_list


# app health page
@app.route("/apphealth", methods=['POST', 'GET'])
def app_health_details():
    if request.method == 'POST':
        ns = request.form['namespace']
        app_name = request.form['app_name']
        host = kiali_url
        wkld_statuses, http_status_code_stats = get_app_health_details(host, ns, app_name)
        ns_list = get_ns_list()

        return render_template("apps.html", ns_list=ns_list, wkld_statuses=wkld_statuses,
                               http_status_code_stats=http_status_code_stats, app_name=app_name)
    else:
        ns_list = get_ns_list()
        if request.args.get('ns'):
            ns = request.args.get('ns')
            app_name = request.args.get('app')
            host = kiali_url
            wkld_statuses, http_status_code_stats = get_app_health_details(host, ns, app_name)

            return render_template("apps.html", ns_list=ns_list, wkld_statuses=wkld_statuses,
                                   http_status_code_stats=http_status_code_stats, app_name=app_name)
        else:
            return render_template("apps.html", ns_list=ns_list)


# get apps in a namespace (for XHR)
@app.route("/getapp")
def apps_in_namespace():
    namespace = request.args.get("ns")
    app_list = get_app_list(namespace)

    return jsonify(sorted(app_list))


# RED page
@app.route("/red")
def red_dash():
    # stats for app RED
    app_red_obj = read_yaml('app_red.yaml')
    red_rate_list = list()
    for item in app_red_obj['rate']:
        red_rate_list.append([item['namespace'], item['app'], item['rate']])
    red_error_list = list()
    for item in app_red_obj['error']:
        red_error_list.append([item['namespace'], item['app'], item['error']])
    red_duration_list = list()
    for item in app_red_obj['duration']:
        red_duration_list.append([item['namespace'], item['app'], item['duration']])

    return render_template("red.html", red_rate_list=red_rate_list,
                           red_error_list=red_error_list, red_duration_list=red_duration_list)


# main driver function
if __name__ == '__main__':
    # get istio enables apps - Immediate first instance
    get_istio_applications(kiali_url)
    app.run(host='0.0.0.0', port=5000, debug=True)
