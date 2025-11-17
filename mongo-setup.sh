#!/bin/bash

# MongoDB connection info
MONGO_HOST="localhost"
MONGO_PORT="27017"
DB_NAME="health_db"

# Collections to create
declare -A COLLECTIONS
COLLECTIONS=( ["heart_rate"]="minutes" ["calories"]="minutes" ["steps"]="minutes" )

# Iterate and create collections
for COLLECTION in "${!COLLECTIONS[@]}"; do
  echo "Creating time-series collection: $COLLECTION"
  mongo --quiet --host $MONGO_HOST --port $MONGO_PORT <<EOF
use $DB_NAME
db.createCollection("$COLLECTION", {
    timeseries: {
        timeField: "time",
        metaField: "user_id",
        granularity: "${COLLECTIONS[$COLLECTION]}"
    }
})
EOF
done

echo "All collections created successfully."
