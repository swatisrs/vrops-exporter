from BaseCollector import BaseCollector
from tools.Vrops import Vrops
import os


class HostSystemStatsCollector(BaseCollector):

    def __init__(self):
        super().__init__()
        self.vrops_entity_name = 'hostsystem'
        self.wait_for_inventory_data()
        self.name = self.__class__.__name__

    def collect(self):
        gauges = self.generate_gauges('stats', self.name, self.vrops_entity_name,
                                      [self.vrops_entity_name, 'vcenter', 'datacenter', 'vccluster'])
        if not gauges:
            return

        if os.environ['DEBUG'] >= '1':
            print(self.name, 'starts with collecting the metrics')

        token = self.get_target_tokens()
        token = token[self.target]
        if not token:
            print("skipping " + self.target + " in " + self.name + ", no token")

        uuids = self.get_hosts_by_target()
        for metric_suffix in gauges:
            statkey = gauges[metric_suffix]['statkey']
            values = Vrops.get_latest_stat_multiple(self.target, token, uuids, statkey)
            if not values:
                print("skipping statkey " + str(statkey) + " in", self.name, ", no return")
                continue

            for value_entry in values:
                metric_value = value_entry['stat-list']['stat'][0]['data']
                if metric_value:
                    metric_value = metric_value[0]
                    host_id = value_entry['resourceId']
                    gauges[metric_suffix]['gauge'].add_metric(
                        labels=[self.hosts[host_id]['name'],
                                self.hosts[host_id]['vcenter'],
                                self.hosts[host_id]['datacenter'].lower(),
                                self.hosts[host_id]['parent_cluster_name']],
                        value=metric_value)

        for metric_suffix in gauges:
            yield gauges[metric_suffix]['gauge']
