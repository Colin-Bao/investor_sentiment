apt update
apt install mysql-server
systemctl start mysql.service
use mysql
select host, user, authentication_string from user;
update user set host = '%' where user = 'root';
vim /etc/mysql/mysql.conf.d
bind-address = 127.0.0.1
sysctl.conf
sysctl -p
systemctl restart mysql.service
conda install -c conda-forge mysql-connector-python

SHOW VARIABLES LIKE 'validate_password%';

SET GLOBAL validate_password.length = 4;
SET GLOBAL validate_password.number_count = 0;
SET GLOBAL validate_password.mixed_case_count=0;
SET GLOBAL validate_password.special_char_count=0;
SET GLOBAL validate_password.policy=0;

ALTER USER 'root'@'%' IDENTIFIED WITH mysql_native_password BY '1111';
mysql_secure_installation