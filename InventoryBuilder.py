import json, os
from flask import Flask, request, abort, jsonify
from gevent.pywsgi import WSGIServer
import re, yaml, sys, time
import traceback
import requests
from threading import Thread
from resources.Vcenter import Vcenter
from tools.Resources import Resources
from urllib.parse import urlparse, parse_qs
from urllib3 import disable_warnings, exceptions
from urllib3.exceptions import HTTPError


class InventoryBuilder:
    def __init__(self, json):
        self.json = json
        self._user = os.environ["USER"]
        self._password = os.environ["PASSWORD"]
        self.vcenter_list = list()
        self.target_tokens = dict()
        self.get_vrops()

        thread = Thread(target=self.run_rest_server)
        thread.start()

        self.query_inventory_permanent()

    def run_rest_server(self):
        collectors = []
        metrics = []

        app = Flask(__name__)
        print('serving /vrops_list on 8000')

        @app.route('/vrops_list', methods=['GET'])
        def vrops_list():
            return json.dumps(self.vrops_list)

        print('serving /inventory on 8000')

        @app.route('/vcenters', methods=['GET'])
        def vcenters():
            return self.vcenters

        @app.route('/datacenters', methods=['GET'])
        def datacenters():
            return self.datacenters

        @app.route('/clusters', methods=['GET'])
        def clusters():
            return self.clusters

        @app.route('/hosts', methods=['GET'])
        def hosts():
            return self.hosts

        @app.route('/datastores', methods=['GET'])
        def datastores():
            return self.datastores

        @app.route('/vms', methods=['GET'])
        def vms():
            return self.vms

        @app.route('/iteration', methods=['GET'])
        def iteration():
            return str(self.iteration)

        @app.route('/register', methods=['POST'])
        def post_registered_collectors():
            if not request.json:
                abort(400)
            collector = {
                'collector': request.json["collector"],
                'metrics': request.json["metric_names"]
            }
            collectors.append(collector)
            return jsonify({"collectors registered": collectors})

        @app.route('/register', methods=['GET'])
        def get_registered_collectors():
            return jsonify({"collectors registered": collectors})

        @app.route('/metrics', methods=['POST'])
        def collect_metric_names():
            if not request.json:
                abort(400)
            metric = {
                'metric_name': request.json['metric_name']
            }
            metrics.append(metric)
            return jsonify({"collector metrics names ": metrics})

        @app.route('/metrics', methods=['GET'])
        def get_metric_names():
            return jsonify({"metrics": metrics})

        @app.route('/metrics', methods=['DELETE'])
        def delete_metric_names():
            metrics.clear()
            return jsonify({"metrics": metrics})


        #FIXME: this could basically be the always active token list. no active token? refresh!
        @app.route('/target_tokens', methods=['GET'])
        def token():
            return json.dumps(self.target_tokens)

        if os.environ['DEBUG'] >= '2':
            WSGIServer(('127.0.0.1', 8000), app).serve_forever()
        else:
            WSGIServer(('127.0.0.1', 8000), app, log=None).serve_forever()
        # WSGIServer(('0.0.0.0', 8000), app).serve_forever()

    def get_vrops(self):
        with open(self.json) as json_file:
            netbox_json = json.load(json_file)
        vrops_list = list()
        for target in netbox_json:
            if target['labels']['job'] == "vrops":
                vrops = target['labels']['server_name']
                vrops_list.append(vrops)
        self.vrops_list = vrops_list

    def query_inventory_permanent(self):
        self.iteration = 0
        while True:
            threads_vc = list()
            if os.environ['DEBUG'] >= '1':
                print("real run " + str(self.iteration))
            for vrops in self.vrops_list:
                if not self.query_vrops(vrops):
                    print("retrying connection to " + vrops + " in next iteration")
            self.get_vcenters()
            self.get_datacenters()
            self.get_clusters()
            self.get_hosts()
            self.get_datastores()
            self.get_vms()
            self.iteration += 1
            time.sleep(180)

    def query_vrops(self, vrops):
        if os.environ['DEBUG'] >= '1':
            print("querying " + vrops)
        token = Resources.get_token(target=vrops)
        if not token:
            return False
        self.target_tokens[vrops] = token
        vcenter = self.create_resource_objects(vrops, token)
        self.vcenter_list.append(vcenter)
        return True

    def create_resource_objects(self, vrops, token):
        for adapter in Resources.get_adapter(target=vrops, token=token):
            if os.environ['DEBUG'] >= '2':
                print("Collecting vcenter: " + adapter['name'])
            vcenter = Vcenter(target=vrops, token=token, name=adapter['name'], uuid=adapter['uuid'])
            vcenter.add_datacenter()
            for dc_object in vcenter.datacenter:
                if os.environ['DEBUG'] >= '2':
                    print("Collecting Datacenter: " + dc_object.name)
                dc_object.add_cluster()
                threads = list()
                for cl_object in dc_object.clusters:
                    if os.environ['DEBUG'] >= '2':
                        print("Collecting Cluster: " + cl_object.name)
                    thread = Thread(target=self.fetch_hosts_parallel,args=(cl_object,))
                    thread.start()
                    threads.append(thread)
                for t in threads:
                    t.join()
            return vcenter

    def fetch_hosts_parallel(self, cl_object):
        cl_object.add_host()
        for hs_object in cl_object.hosts:
            if os.environ['DEBUG'] >= '2':
                print("Collecting Host: " + hs_object.name)
            hs_object.add_datastore()
            for ds_object in hs_object.datastores:
                if os.environ['DEBUG'] >= '2':
                    print("Collecting Datastore: " + ds_object.name)
            hs_object.add_vm()
            for vm_object in hs_object.vms:
                if os.environ['DEBUG'] >= '2':
                    print("Collecting VM: " + vm_object.name)

    def get_vcenters(self):
        tree = dict()
        for vcenter in self.vcenter_list:
            tree[vcenter.uuid] = {
                    'uuid': vcenter.uuid,
                    'name': vcenter.name,
                    'target': vcenter.target,
                    'token': vcenter.token,
                    }
        self.vcenters = tree
        return tree

    def get_datacenters(self):
        tree = dict()
        for vcenter in self.vcenter_list:
            for dc in vcenter.datacenter:
                tree[dc.name] = {
                        'uuid': dc.uuid,
                        'name': dc.name,
                        'parent_vcenter_uuid': vcenter.uuid,
                        'parent_vcenter_name': vcenter.name,
                        'target': dc.target,
                        'token': dc.token,
                        }
        self.datacenters = tree
        return tree

    def get_clusters(self):
        tree = dict()
        for vcenter in self.vcenter_list:
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    tree[cluster.uuid] = {
                            'uuid': cluster.uuid,
                            'name': cluster.name,
                            'parent_dc_uuid': dc.uuid,
                            'parent_dc_name': dc.name,
                            'vcenter': vcenter.name,
                            'target': cluster.target,
                            'token': cluster.token,
                            }
        self.clusters = tree
        return tree

    def get_hosts(self):
        tree = dict()
        for vcenter in self.vcenter_list:
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    for host in cluster.hosts:
                        tree[host.uuid] = {
                                'uuid': host.uuid,
                                'name': host.name,
                                'parent_cluster_uuid': cluster.uuid,
                                'parent_cluster_name': cluster.name,
                                'datacenter': dc.name,
                                'target': host.target,
                                'token': host.token,
                                }
        self.hosts = tree
        return tree

    def get_datastores(self):
        tree = dict()
        for vcenter in self.vcenter_list:
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    for host in cluster.hosts:
                        for ds in host.datastores:
                            tree[ds.uuid] = {
                                    'uuid': ds.uuid,
                                    'name': ds.name,
                                    'parent_host_uuid': host.uuid,
                                    'parent_host_name': host.name,
                                    'cluster': cluster.name,
                                    'datacenter': dc.name,
                                    'target': ds.target,
                                    'token': ds.token,
                                    }
        self.datastores = tree
        return tree

    def get_vms(self):
        tree = dict()
        for vcenter in self.vcenter_list:
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    for host in cluster.hosts:
                        for vm in host.vms:
                            tree[vm.uuid] = {
                                    'uuid': vm.uuid,
                                    'name': vm.name,
                                    'parent_host_uuid': host.uuid,
                                    'parent_host_name': host.name,
                                    'cluster': cluster.name,
                                    'datacenter': dc.name,
                                    'target': vm.target,
                                    'token': vm.token,
                                    }
        self.vms = tree
        return tree
