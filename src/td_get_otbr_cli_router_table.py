import os
import subprocess
import json

from td_parse_extaddr_data_map import parse_extaddr_nodename_mapping
import td_util_ot_ctl

def get_thread_router_table():
    try:
        # Executes the command: ot-ctl router table
        output = td_util_ot_ctl.run_ot_ctl_stdio("router table")
        return output
    except subprocess.CalledProcessError as e:
        print(f"Error running ot-ctl: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error running ot-ctl: {e}")
        raise

def parse_router_table_output(output, extaddr_map=None):
    """
    Parses the router table output into a list of router dictionaries.
    
    Expected format:
    | ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC     | Link |
    +----+--------+----------+-----------+-------+--------+-----+------------------+------+
    |  1 | 0x0400 |       25 |         1 |     2 |      3 |  20 | 8e3b369df65e9496 |    1 |
    
    Args:
        output: Router table output text
        extaddr_map: Optional dictionary mapping extended MAC to node name
        
    Returns:
        List of router dictionaries
        
    Raises:
        TypeError: If output is not a string
    """
    if not isinstance(output, str):
        raise TypeError(f"Expected output to be a string, got {type(output).__name__}")
    
    routers = []
    if extaddr_map is None:
        extaddr_map = {}
    lines = output.strip().split('\n')
    
    # Find the header line (contains "ID" and "RLOC16")
    header_line = None
    header_idx = 0
    for i, line in enumerate(lines):
        if 'ID' in line and 'RLOC16' in line:
            header_line = line
            header_idx = i
            break
    
    if not header_line:
        return routers
    
    # Extract field names from the header line
    # Header format: "| ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC     | Link |"
    field_names = [f.strip() for f in header_line.split('|')[1:-1]]
    
    # Parse data rows (skip header and separator lines)
    for line in lines[header_idx + 2:]:
        # Skip separator lines (lines starting with +)
        if line.startswith('+') or not line.strip():
            continue
        
        # Skip header-like lines
        if 'ID' in line or 'RLOC16' in line:
            continue
        
        # Split by pipe and extract values
        values = [v.strip() for v in line.split('|')[1:-1]]
        
        # Only process lines with the correct number of fields
        if len(values) == len(field_names):
            router = {}
            for field_name, value in zip(field_names, values):
                # Try to convert to int if it's a numeric field
                try:
                    if field_name in ['ID', 'Path Cost', 'LQ In', 'LQ Out', 'Age', 'Link']:
                        router[field_name] = int(value)
                    else:
                        # Conform RLOC16 key and value are stored in lowercase for consistent mapping
                        if field_name == 'RLOC16':
                            router["rloc16"] = value.lower()  # Normalize RLOC16 to lowercase for consistent mapping
                        else:
                            router[field_name] = value
                except ValueError:
                    router[field_name] = value
            
            # Get device_label from extaddr_map if available
            ext_mac = router.get('Extended MAC', '').lower()
            # Normalize to extaddr field name
            if ext_mac:
                router['extaddr'] = ext_mac
            # Add device_label from extaddr_map if available
            if ext_mac and ext_mac in extaddr_map:
                router['device_label'] = extaddr_map[ext_mac]
            
            routers.append(router)
    
    return routers

def get_router_table_data(extaddr_map=None):
    """
    Retrieves and parses the thread router table data.
    
    Args:
        extaddr_map: Optional dictionary mapping extended MAC to node name
    
    Returns:
        List of router dictionaries with parsed data
        
    Raises:
        Exception: If retrieving or parsing router table fails
    """
    raw_output = get_thread_router_table()
    if not raw_output:
        raise ValueError("Router table output is empty")
    return parse_router_table_output(raw_output, extaddr_map)

if __name__ == "__main__":
    try:
        
        # Load extaddr to nodename mapping from JSON file
        extaddr_json_filename = "td-static-extaddr-device-label.json"

        extaddr_file = extaddr_json_filename
        if os.path.exists(extaddr_file):
            print(f"Loading extended address to node name mapping from {extaddr_file}...")
            extaddr_map = parse_extaddr_nodename_mapping(extaddr_file)
        else:
            print(f"ExtAddr mapping file not found: {extaddr_file}. Continuing with empty map.")
            extaddr_map = {}
            
        router_table_data = get_router_table_data(extaddr_map)
        save_path = "td-otbr-cli-router-table.json"
        with open(save_path, 'w') as f:
            json.dump(router_table_data, f, indent=4)
        print(json.dumps(router_table_data, indent=4))
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON - {e}")
    except IOError as e:
        print(f"Error: I/O error - {e}")
    except Exception as e:
        print(f"Error: {e}")
