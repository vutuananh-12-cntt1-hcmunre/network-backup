from getpass import getpass
from netmiko import ConnectHandler

device = {
    "device_type": "linux",
    "host": "192.168.234.131",
    "username": input("SSH username: ").strip(),
    "password": getpass("SSH password: "),
    "conn_timeout": 10,
    "auth_timeout": 10,
    "banner_timeout": 15,
}

try:
    with ConnectHandler(**device) as connection:
        print("\n=== HOSTNAME ===")
        print(connection.send_command("hostname"))

        print("\n=== SYSTEM ===")
        print(connection.send_command("uname -a"))

        print("\n=== IP ADDRESS ===")
        print(connection.send_command("hostname -I"))

except Exception as error:
    print(f"SSH test failed: {error}")