import requests


# call Kiali API and return response
def call_kiali_api(kialiHost, endpoint):
    api_url = kialiHost + "/kiali/api" + endpoint
    r = requests.get(api_url)
    return r.json()
