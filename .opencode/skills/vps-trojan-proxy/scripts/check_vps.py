import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('134.122.190.35', 22, 'root', 'Brian52026$$', timeout=15)

def run(cmd):
    print(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd)
    print(stdout.read().decode())
    print(stderr.read().decode())

run("systemctl is-active trojan trojan-web nginx 2>&1")
run("ss -tlnp | grep -E '22|80|443|444|8080|33609' 2>&1")
run("cat /usr/local/etc/trojan/config.json 2>&1")
run("ls -la /etc/nginx/conf.d/ 2>&1")
run("cat /etc/nginx/conf.d/study.conf 2>&1")
run("cat /etc/nginx/conf.d/webssl.conf 2>&1")

client.close()