import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('134.122.190.35', 22, 'root', 'Brian52026$$', timeout=15)

def run(cmd):
    print(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd)
    print(stdout.read().decode())
    print(stderr.read().decode())

run("ls -la /root/.acme.sh/aiwanxiang.top_ecc/ 2>&1")
run("openssl x509 -in /root/.acme.sh/aiwanxiang.top_ecc/fullchain.cer -noout -dates 2>&1")
run("ls -la /etc/nginx/ssl/ 2>&1")
run("openssl x509 -in /etc/nginx/ssl/fullchain.cer -noout -dates 2>&1")
run("ls -la /usr/share/nginx/html/study/ 2>&1")
run("head -5 /usr/share/nginx/html/study/index.html 2>&1")
run("cat /etc/systemd/system/trojan-web.service 2>&1")
run("docker ps 2>&1")

client.close()