from urllib3 import disable_warnings
from urllib3 import exceptions
from tools.helper import chunk_list
from threading import Thread
import requests
import json
import os


class Vrops:
    def get_token(target):
        url = "https://" + target + "/suite-api/api/auth/token/acquire"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json"
        }
        payload = {
            "username": os.environ['USER'],
            "authSource": "Local",
            "password": os.environ['PASSWORD']
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.post(url,
                                     data=json.dumps(payload),
                                     verify=False,
                                     headers=headers,
                                     timeout=10)
        except Exception as e:
            if os.environ['DEBUG'] >= '1':
                print("Problem connecting to " + target + ' Error: ' + str(e))
            return False

        if response.status_code == 200:
            return response.json()["token"]
        else:
            if os.environ['DEBUG'] >= '1':
                print("problem getting token " + str(target) + ": " + response.text)
            return False

    def get_adapter(target, token):
        url = "https://" + target + "/suite-api/api/adapters"
        querystring = {
            "adapterKindKey": "VMWARE"
        }
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        adapters = list()
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.get(url,
                                    params=querystring,
                                    verify=False,
                                    headers=headers)
        except Exception as e:
            print("Problem connecting to " + target + ' Error: ' + str(e))
            return False

        if response.status_code == 200:
            for resource in response.json()["adapterInstancesInfoDto"]:
                res = dict()
                res['name'] = resource["resourceKey"]["name"]
                res['uuid'] = resource["id"]
                res['adapterkind'] = resource["resourceKey"]["adapterKindKey"]
                adapters.append(res)
        else:
            print("problem getting adapter " + str(target))
            return False

        return adapters

    def get_resources(self, target, token, resourcekind, parentid):
        url = "https://" + target + "/suite-api/api/resources"
        querystring = {
            'parentId': parentid,
            'adapterKind': 'VMware',
            'resourceKind': resourcekind,
            'pageSize': '50000'
        }
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        resources = list()
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.get(url,
                                    params=querystring,
                                    verify=False,
                                    headers=headers)
        except Exception as e:
            print("Problem connecting to " + target + "Error: " + str(e))
            return resources

        if response.status_code == 200:
            try:
                resourcelist = response.json()["resourceList"]
                for resource in resourcelist:
                    res = dict()
                    res['name'] = resource["resourceKey"]["name"]
                    res['uuid'] = resource["identifier"]
                    resources.append(res)
            except json.decoder.JSONDecodeError as e:
                print("Catching JSONDecodeError for target:", str(target), "and resourcekind:", str(resourcekind),
                      "\nerror msg:", str(e))
        else:
            print("problem getting resource " + str(response.json()))
        return resources

    def get_project_ids(target, token, uuids):
        if not isinstance(uuids, list):
            print("Error in get project_ids: uuids must be a list with multiple entries")
            return False
        # vrops can not handle more than 1000 uuids
        uuids_chunked = list(chunk_list(uuids, 1000))
        project_ids = list()
        url = "https://" + target + "/suite-api/api/resources/bulk/relationships"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        import queue
        q = queue.Queue()
        thread_list = list()
        chunk_iteration = 0
        for uuid_list in uuids_chunked:
            chunk_iteration += 1
            t = Thread(target=Vrops.get_project_id_chunk,
                       args=(q, uuid_list, url, headers, target, chunk_iteration))
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()

        while not q.empty():
            project_ids += q.get()
        return project_ids

    def get_datacenter(self, target, token, parentid):
        return self.get_resources(target, token, parentid=parentid, resourcekind="Datacenter")

    def get_cluster(self, target, token, parentid):
        return self.get_resources(target, token, parentid=parentid, resourcekind="ClusterComputeResource")

    def get_hosts(self, target, token, parentid):
        return self.get_resources(target, token, parentid=parentid, resourcekind="HostSystem")

    def get_datastores(self, target, token, parentid):
        return self.get_resources(target, token, parentid=parentid, resourcekind="Datastore")

    def get_virtualmachines(self, target, token, parentid):
        return self.get_resources(target, token, parentid=parentid, resourcekind="VirtualMachine")

    def get_project_folders(self, target, token):
        return self.get_resources(target, token, parentid=None, resourcekind="VMFolder")

    # not recommended
    def get_latest_stat(target, token, uuid, key):
        url = "https://" + target + "/suite-api/api/resources/" + uuid + "/stats/latest"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.get(url,
                                    verify=False,
                                    headers=headers,
                                    timeout=10)
        except Exception as e:
            print("Problem getting stats error for", key, str(e))
            return False

        if response.status_code == 200:
            for statkey in response.json()["values"][0]["stat-list"]["stat"]:
                if statkey["statKey"]["key"] is not None and statkey["statKey"]["key"] == key:
                    return statkey["data"][0]
        else:
            print("Return code not 200 for " + str(key) + ": " + str(response.json()))
            return False

    # this is for a single query of a property and returns the value only
    def get_property(target, token, uuid, key):
        url = "https://" + target + "/suite-api/api/resources/" + uuid + "/properties"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.get(url,
                                    verify=False,
                                    headers=headers)
        except Exception as e:
            print("Problem getting stats Error: " + str(e))
            return False

        if response.status_code == 200:
            for propkey in response.json()["property"]:
                if propkey["name"] is not None and propkey["name"] == key:
                    return propkey["value"]
        else:
            print("Return code not 200 for " + str(key) + ": " + str(response.json()))
            return False

    # if we expect a number without special characters
    def get_latest_number_properties_multiple(target, token, uuids, propkey):
        if not isinstance(uuids, list):
            print("Error in get multiple: uuids must be a list with multiple entries")
            return False

        return_list = list()
        url = "https://" + target + "/suite-api/api/resources/properties/latest/query"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        payload = {
            "resourceIds": uuids,
            "propertyKeys": [propkey]
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.post(url,
                                     data=json.dumps(payload),
                                     verify=False,
                                     headers=headers)
        except Exception as e:
            print("Problem getting property Error: " + str(e))
            return False

        if response.status_code == 200:
            try:
                if not response.json()['values']:
                    print("skipping propkey " + str(propkey) + ", no return")
                    return False
            except json.decoder.JSONDecodeError as e:
                print("Catching JSONDecodeError for target:", str(target), "and key:", str(propkey),
                      "\nerror msg:", str(e))
                return False
            for resource in response.json()['values']:
                d = dict()
                d['resourceId'] = resource['resourceId']
                d['propkey'] = propkey
                content = resource['property-contents']['property-content']
                if content:
                    if 'values' in content[0]:
                        d['data'] = content[0]['values'][0]
                    else:
                        d['data'] = content[0]['data'][0]
                else:
                    # resources can go away, so None is returned
                    print("skipping resource for get", str(propkey))
                return_list.append(d)
            return return_list
        else:
            print("Return code not 200 for " + str(propkey) + ": " + response.text)
            return False

    # if the property describes a status that has several states
    # the expected status returns a 0, all others become 1
    def get_latest_enum_properties_multiple(target, token, uuids, propkey):

        if not isinstance(uuids, list):
            print("Error in get multiple: uuids must be a list with multiple entries")
            return False

        url = "https://" + target + "/suite-api/api/resources/properties/latest/query"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        payload = {
            "resourceIds": uuids,
            "propertyKeys": [propkey]
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.post(url,
                                     data=json.dumps(payload),
                                     verify=False,
                                     headers=headers)
        except Exception as e:
            print("Problem getting property Error: " + str(e))
            return False

        properties_list = list()

        if response.status_code == 200:
            try:
                if not response.json()['values']:
                    print("skipping propkey " + str(propkey) + ", no return")
                    return False
            except json.decoder.JSONDecodeError as e:
                print("Catching JSONDecodeError for target:", str(target), "and key:", str(propkey),
                      "\nerror msg:", str(e))
                return False
            for resource in response.json()['values']:
                d = dict()
                d['resourceId'] = resource['resourceId']
                d['propkey'] = propkey
                content = resource['property-contents']['property-content']
                if content:
                    if 'values' in content[0]:
                        d['value'] = content[0]['values'][0]
                else:
                    # resources can go away, so None is returned
                    print("skipping resource for get", str(propkey))
                properties_list.append(d)
            return properties_list
        else:
            print("Return code not 200 for " + str(propkey) + ": " + response.text)
            return False

    # for all other properties that return a string or numbers with special characters
    def get_latest_info_properties_multiple(target, token, uuids, propkey):

        if not isinstance(uuids, list):
            print("Error in get multiple: uuids must be a list with multiple entries")
            return False

        url = "https://" + target + "/suite-api/api/resources/properties/latest/query"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }
        payload = {
            "resourceIds": uuids,
            "propertyKeys": [propkey]
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.post(url,
                                     data=json.dumps(payload),
                                     verify=False,
                                     headers=headers)
        except Exception as e:
            print("Problem getting property Error: " + str(e))
            return False

        properties_list = list()

        if response.status_code == 200:
            try:
                if not response.json()['values']:
                    print("skipping propkey " + str(propkey) + ", no return")
                    return False
            except json.decoder.JSONDecodeError as e:
                print("Catching JSONDecodeError for target:", str(target), "and key:", str(propkey),
                      "\nerror msg:", str(e))
                return False
            for resource in response.json()['values']:
                d = dict()
                d['resourceId'] = resource['resourceId']
                d['propkey'] = propkey
                content = resource['property-contents']['property-content']
                if content:
                    if 'values' in content[0]:
                        info = content[0]['values'][0]
                    else:
                        info = 'None'
                    d['data'] = info
                else:
                    # resources can go away, so None is returned
                    print("skipping resource for get", str(propkey))
                properties_list.append(d)
            return properties_list
        else:
            print("Return code not 200 for " + str(propkey) + ": " + response.text)
            return False

    def get_latest_stat_multiple(target, token, uuids, key):
        if not isinstance(uuids, list):
            print("Error in get multiple: uuids must be a list with multiple entries")
            return False

        # vrops can not handle more than 1000 uuids
        uuids_chunked = list(chunk_list(uuids, 1000))
        return_list = list()
        url = "https://" + target + "/suite-api/api/resources/stats/latest/query"
        headers = {
            'Content-Type': "application/json",
            'Accept': "application/json",
            'Authorization': "vRealizeOpsToken " + token
        }

        import queue
        q = queue.Queue()
        thread_list = list()
        chunk_iteration = 0
        for uuid_list in uuids_chunked:
            chunk_iteration += 1
            t = Thread(target=Vrops.get_stat_chunk,
                       args=(q, uuid_list, url, headers, key, target, chunk_iteration))
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()

        while not q.empty():
            return_list += q.get()
        return return_list

    def get_project_id_chunk(q, uuid_list, url, headers, target, chunk_iteration):
        if os.environ['DEBUG'] >= '2':
            print(target, 'chunk:', chunk_iteration)

        payload = {
            "relationshipType": "ANCESTOR",
            "resourceIds": uuid_list,
            "resourceQuery": {
                "name": ["Project"],
                "adapterKind": ["VMWARE"],
                "resourceKind": ["VMFolder"]
            },
            "hierarchyDepth": 5
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.post(url,
                                     data=json.dumps(payload),
                                     verify=False,
                                     headers=headers)
        except Exception as e:
            print("Problem getting project folder Error: " + str(e))
            return False
        if response.status_code == 200:
            try:
                for project in response.json()['resourcesRelations']:
                    p_ids = dict()
                    for vm_uuid in project["relatedResources"]:
                        p_ids[vm_uuid] = project["resource"]["resourceKey"]["name"][
                                          project["resource"]["resourceKey"]["name"].find("(") + 1:
                                          project["resource"]["resourceKey"]["name"].find(")")]
                    q.put([p_ids])
            except json.decoder.JSONDecodeError as e:
                print("Catching JSONDecodeError for target:", str(target),
                      "chunk_iteration:", str(chunk_iteration), "\nerror msg:", str(e))
                return False
        else:
            print("Return code not 200 for: " + response.text)
            return False

    def get_stat_chunk(q, uuid_list, url, headers, key, target, chunk_iteration):
        if os.environ['DEBUG'] >= '2':
            print(target, key, 'chunk:', chunk_iteration)

        payload = {
            "resourceId": uuid_list,
            "statKey": [key]
        }
        disable_warnings(exceptions.InsecureRequestWarning)
        try:
            response = requests.post(url,
                                     data=json.dumps(payload),
                                     verify=False,
                                     headers=headers,
                                     timeout=10)
        except Exception as e:
            print("Problem getting stats Error for", key, str(e))
            return False

        if response.status_code == 200:
            try:
                q.put(response.json()['values'])
            except json.decoder.JSONDecodeError as e:
                print("Catching JSONDecodeError for target:", str(target), "and key:", str(key),
                      "chunk_iteration:", str(chunk_iteration), "\nerror msg:", str(e))
                return False
        else:
            print("Return code not 200 for " + str(key) + ": " + response.text)
            return False
