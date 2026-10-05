import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('134.122.190.35', 22, 'root', 'Brian52026$$', timeout=15)

stdin, stdout, stderr = client.exec_command('docker exec trojan-mariadb mysql -uroot -pyZRgavHy -e "SELECT COUNT(*) FROM trojan.users" 2>&1')
print(stdout.read().decode())
print(stderr.read().decode())

client.close()