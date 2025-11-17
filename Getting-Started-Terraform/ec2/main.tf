/*
This Terraform configuration creates a VPC + public subnet + route to IGW,
a security group (HTTP + SSH), and an EC2 instance that boots Kafka (KRaft)
plus Spark + your ingestion pipeline.
*/

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

##################################################################################
# PROVIDER
##################################################################################

provider "aws" {
  region = var.aws_region
}

##################################################################################
# DATA
##################################################################################

data "aws_ssm_parameter" "amzn2_linux" {
  name = "/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2"
}

##################################################################################
# NETWORKING
##################################################################################

resource "aws_vpc" "app" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_hostnames = var.vpc_enable_dns_hostnames
}

resource "aws_internet_gateway" "app" {
  vpc_id = aws_vpc.app.id
}

resource "aws_subnet" "public_subnet1" {
  cidr_block              = var.vpc_subnet_cidr
  vpc_id                  = aws_vpc.app.id
  map_public_ip_on_launch = var.map_public_ip_on_launch
}

# Route table with default route to Internet Gateway
resource "aws_route_table" "app" {
  vpc_id = aws_vpc.app.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.app.id
  }
}

resource "aws_route_table_association" "app_subnet1" {
  subnet_id      = aws_subnet.public_subnet1.id
  route_table_id = aws_route_table.app.id
}

##################################################################################
# SECURITY GROUP  ✅ ajouté / remis ici
##################################################################################

resource "aws_security_group" "nginx_sg" {
  name        = "nginx_sg"
  description = "Allow HTTP and SSH"
  vpc_id      = aws_vpc.app.id

  # HTTP (port pour l’API)
  ingress {
    from_port   = var.http_port
    to_port     = var.http_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Tout trafic sortant autorisé
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "nginx_sg"
  }
}

##################################################################################
# EC2 INSTANCE
##################################################################################

resource "aws_instance" "nginx1" {
  ami                         = nonsensitive(data.aws_ssm_parameter.amzn2_linux.value)
  instance_type               = var.ec2_instance_type
  subnet_id                   = aws_subnet.public_subnet1.id
  vpc_security_group_ids      = [aws_security_group.nginx_sg.id]
  user_data_replace_on_change = true

  # si tu as ajouté un IAM instance_profile, garde-le ici
  # iam_instance_profile        = aws_iam_instance_profile.ec2_instance_profile.name

  user_data = <<-EOF
#!/bin/bash
set -euxo pipefail

APP_DIR="/opt/app"
BUCKET_NAME="${var.bucket_name}"

########################################
# 1) Linux & outils de base
########################################
yum update -y
yum install -y \
  java-17-amazon-corretto-headless \
  python3 python3-pip \
  awscli \
  tar gzip

########################################
# 2) Kafka en mode KRaft (localhost:9092)
########################################
KVER="3.7.0"
cd /opt
curl -L -o kafka.tgz https://downloads.apache.org/kafka/$${KVER}/kafka_2.13-$${KVER}.tgz
tar -xzf kafka.tgz
mv kafka_2.13-$${KVER} kafka
rm -f kafka.tgz

useradd -r -s /sbin/nologin kafka || true
chown -R kafka:kafka /opt/kafka

CLUSTER_ID=$(/opt/kafka/bin/kafka-storage.sh random-uuid)

cat >/opt/kafka/config/kraft.properties <<KCFG
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@localhost:9093
listeners=PLAINTEXT://0.0.0.0:9092,CONTROLLER://localhost:9093
inter.broker.listener.name=PLAINTEXT
controller.listener.names=CONTROLLER
log.dirs=/opt/kafka/data
num.partitions=1
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
group.initial.rebalance.delay.ms=0
auto.create.topics.enable=false
KCFG

mkdir -p /opt/kafka/data
/opt/kafka/bin/kafka-storage.sh format -t $${CLUSTER_ID} -c /opt/kafka/config/kraft.properties

cat >/etc/systemd/system/kafka.service <<KSVC
[Unit]
Description=Apache Kafka (KRaft) single-node
After=network.target
[Service]
User=kafka
Group=kafka
Environment=KAFKA_HEAP_OPTS=-Xmx1024m -Xms512m
ExecStart=/opt/kafka/bin/kafka-server-start.sh /opt/kafka/config/kraft.properties
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
KSVC

systemctl daemon-reload
systemctl enable --now kafka

# attendre que le port 9092 soit ouvert
for i in {1..30}; do (echo > /dev/tcp/127.0.0.1/9092) >/dev/null 2>&1 && break || sleep 2; done

# créer les topics
/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic heartrate --partitions 1 --replication-factor 1 || true
/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic calories  --partitions 1 --replication-factor 1 || true
/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic steps     --partitions 1 --replication-factor 1 || true

########################################
# 3) Apache Spark (local[*])
########################################
SPARK_VERSION="3.5.1"
HADOOP_VERSION="3"
cd /opt
curl -L -o spark.tgz https://downloads.apache.org/spark/spark-$${SPARK_VERSION}/spark-$${SPARK_VERSION}-bin-hadoop$${HADOOP_VERSION}.tgz
tar -xzf spark.tgz
mv spark-$${SPARK_VERSION}-bin-hadoop$${HADOOP_VERSION} spark
rm -f spark.tgz

cat >/etc/profile.d/spark.sh <<'SPENV'
export SPARK_HOME=/opt/spark
export PATH=$PATH:/opt/spark/bin
SPENV

source /etc/profile.d/spark.sh

########################################
# 4) Récupérer ton code depuis S3
########################################
mkdir -p $APP_DIR
# si pas d'IAM role, cette commande échouera -> dans ce cas tu feras le sync à la main après ssh
aws s3 sync s3://$BUCKET_NAME/app $APP_DIR || true
chown -R ec2-user:ec2-user $APP_DIR

########################################
# 5) Environnement Python + dépendances
########################################
python3 -m venv $APP_DIR/venv
source $APP_DIR/venv/bin/activate
pip install --upgrade pip

pip install fastapi "uvicorn[standard]" kafka-python pandas requests \
           pyspark firebase-admin "python-jose[cryptography]" "passlib[bcrypt]"

# adapter si ton fichier JSON firebase est différent
echo 'export FIREBASE_SERVICE_ACCOUNT_KEY_PATH="/opt/app/cstam2-1f2ec-firebase-adminsdk-fbsvc-2ab61a7ed6.json"' >> /etc/profile.d/app_env.sh
echo 'export KAFKA_BOOTSTRAP_SERVERS="localhost:9092"' >> /etc/profile.d/app_env.sh
echo 'export SECRET_KEY="your_super_secret_key"' >> /etc/profile.d/app_env.sh

########################################
# 6) Corriger data_cleaning.py pour Kafka local
########################################
# ton script utilise KAFKA_BOOTSTRAP = "kafka:29092"
# on le remplace par localhost:9092
if [ -f "$APP_DIR/data_cleaning.py" ]; then
  sed -i 's/KAFKA_BOOTSTRAP = "kafka:29092"/KAFKA_BOOTSTRAP = "localhost:9092"/' $APP_DIR/data_cleaning.py
fi

########################################
# 7) Services systemd : ingestion_api, simulateur, Spark
########################################

# FastAPI ingestion_api (Kafka producer)
cat >/etc/systemd/system/ingestion-api.service <<AISVC
[Unit]
Description=FastAPI ingestion API
After=network.target kafka.service

[Service]
User=ec2-user
WorkingDirectory=$APP_DIR
Environment="KAFKA_BOOTSTRAP_SERVERS=localhost:9092"
Environment="SECRET_KEY=your_super_secret_key"
ExecStart=$APP_DIR/venv/bin/uvicorn ingestion_api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
AISVC

# Simulateur temps réel -> appelle l'API sur localhost:8000
cat >/etc/systemd/system/realtime-simulator.service <<SIM
[Unit]
Description=Realtime simulator sending data to ingestion_api
After=network.target ingestion-api.service

[Service]
User=ec2-user
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python realtime_simulator.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SIM

# Spark Streaming -> consomme Kafka & exécute data_cleaning.py
cat >/etc/systemd/system/data-cleaning.service <<DCS
[Unit]
Description=Spark streaming data cleaning consuming from Kafka
After=network.target kafka.service

[Service]
User=ec2-user
WorkingDirectory=$APP_DIR
Environment="FIREBASE_SERVICE_ACCOUNT_KEY_PATH=/opt/app/cstam2-1f2ec-firebase-adminsdk-fbsvc-2ab61a7ed6.json"
Environment="PYSPARK_PYTHON=$APP_DIR/venv/bin/python"
ExecStart=/opt/spark/bin/spark-submit --master local[*] $APP_DIR/data_cleaning.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
DCS

########################################
# 8) Activer les services
########################################
systemctl daemon-reload
systemctl enable --now kafka ingestion-api realtime-simulator data-cleaning || true

echo "Bootstrapping terminé : Kafka + Spark + API + simulateur + data_cleaning lancés"
EOF
}
