import json
import td_util_network

if __name__ == "__main__":
    network_dataset_info = td_util_network.get_network_dataset_info()
    save_json_path = "thread-network-dataset-info.json"
    with open(save_json_path, 'w') as f:
        json.dump(network_dataset_info, f, indent=4)
    print(json.dumps(network_dataset_info, indent=4))
