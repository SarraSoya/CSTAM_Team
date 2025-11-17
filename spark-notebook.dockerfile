# Use official Apache Spark image (Spark 3.5.0, Scala 2.12)
FROM apache/spark:3.5.0

USER root

# Install Python and dependencies
RUN apt-get update && \
    apt-get install -y python3-pip wget ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PYSPARK_PYTHON=python3
ENV PYSPARK_DRIVER_PYTHON=python3
ENV SPARK_HOME=/opt/spark

# Install Python packages
RUN pip3 install --upgrade pip && \
    pip3 install jupyterlab ipykernel pandas seaborn matplotlib kafka-python pymongo pyspark google-cloud-firestore

# Download required JARs for Kafka + Mongo integration
RUN mkdir -p ${SPARK_HOME}/jars && cd ${SPARK_HOME}/jars && \
    wget -q https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.12/3.5.0/spark-sql-kafka-0-10_2.12-3.5.0.jar && \
    wget -q https://repo1.maven.org/maven2/org/apache/kafka/kafka-clients/3.5.1/kafka-clients-3.5.1.jar && \
    wget -q https://repo1.maven.org/maven2/org/apache/commons/commons-pool2/2.12.0/commons-pool2-2.12.0.jar && \
    wget -q https://repo1.maven.org/maven2/org/apache/spark/spark-token-provider-kafka-0-10_2.12/3.5.0/spark-token-provider-kafka-0-10_2.12-3.5.0.jar && \
    wget -q https://repo1.maven.org/maven2/org/mongodb/spark/mongo-spark-connector_2.12/10.2.0/mongo-spark-connector_2.12-10.2.0.jar

# Ensure home directory exists and fix ownership (skip user creation)
RUN mkdir -p /home/spark && chown -R spark:spark ${SPARK_HOME} /home/spark

# Switch to non-root user
USER spark

# Expose Jupyter port and set working directory
EXPOSE 8888
WORKDIR ${SPARK_HOME}/work
ENTRYPOINT []
# Start Jupyter Lab by default
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
