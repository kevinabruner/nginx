#!/usr/bin/env python3
import json
import requests

# --- Configuration ---
NETBOX_URL = "https://netbox.thejfk.ca/api"
TOKEN = "18a09ac581f3b2679df0f538698e2893aac493a7"

def get_netbox_data(endpoint):
    headers = {"Authorization": f"Token {TOKEN}", "Accept": "application/json"}
    response = requests.get(f"{NETBOX_URL}/{endpoint}", headers=headers)
    response.raise_for_status()
    return response.json()

def generate_inventory():
    inventory = {
        "_meta": {"hostvars": {}},
        "all": {"children": []}
    }

    vms = get_netbox_data("virtualization/virtual-machines/?limit=1000")
    ips = get_netbox_data("ipam/ip-addresses/?limit=1000")

    # --- 1. Map DB Servers by Environment ---
    # Structure: {"dev": [{"name": "db-dev1", "ip": "10.0.0.1"}, ...], "prod": [...]}
    db_map = {}
    
    for vm in vms.get("results", []):
        vm_name = vm["name"]
        env = vm.get('custom_fields', {}).get('dev_or_prod')
        primary_ip = vm.get("primary_ip4")
        
        # Identify DB servers (adjust logic if 'db-' prefix isn't the only indicator)
        if vm_name.startswith("db-") and env and primary_ip:
            env_key = env.lower()
            if env_key not in db_map:
                db_map[env_key] = []
            
            db_map[env_key].append({
                "hostname": vm_name,
                "ip": primary_ip["address"].split('/')[0]
            })

    # --- 2. Process VIPs (Reverse Proxy Groups) ---
    for ip in ips.get("results", []):
        cf = ip.get('custom_fields', {})
        repo = cf.get('repos_ip')
        env = cf.get('DevorProdIP')
        
        if repo and env:
            target_group = f"{repo}_{env}"
            if target_group not in inventory:
                inventory[target_group] = {"hosts": [], "vars": {}}
                if target_group not in inventory["all"]["children"]:
                    inventory["all"]["children"].append(target_group)
            
            # Standard Vars
            inventory[target_group]["vars"]["vip"] = ip['address'].split('/')[0]
            inventory[target_group]["vars"]["env"] = env
            inventory[target_group]["vars"]["router_id"] = cf.get('router_address')
            
            # NEW: Inject the relevant DB list for this environment
            # This makes 'db_servers' available to your haproxy/nginx templates
            inventory[target_group]["vars"]["db_servers"] = db_map.get(env.lower(), [])

    # --- 3. Process VMs ---
    for vm in vms.get("results", []):
        cf = vm.get('custom_fields', {})
        is_active = vm.get('status', {}).get('value') == 'active'
        repo = cf.get('repos') 
        env = cf.get('dev_or_prod')
        vm_name = vm["name"]
        primary_ip = vm.get("primary_ip4")

        if is_active and primary_ip:
            raw_ip = primary_ip.get("address", "").split("/")[0]
            
            inventory["_meta"]["hostvars"][vm_name] = {
                "ansible_host": raw_ip,
                "netbox_id": vm["id"],
                "proxmox_vmid": cf.get("vmid")
            }

            if repo and isinstance(repo, str):
                target_groups = [repo]
                if env and isinstance(env, str):
                    target_groups.extend([f"{repo}_{env}", env])

                for group in target_groups:
                    if group not in inventory:
                        inventory[group] = {"hosts": [], "vars": {}}
                        if group not in inventory["all"]["children"]:
                            inventory["all"]["children"].append(group)
                    
                    if vm_name not in inventory[group]["hosts"]:
                        inventory[group]["hosts"].append(vm_name)                        

    return inventory

if __name__ == "__main__":
    print(json.dumps(generate_inventory(), indent=2))