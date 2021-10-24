import os

import boto3

BUCKET = 'syncprojects'
ACCESS_ID = os.getenv('ACCESS_ID')
SECRET_KEY = os.getenv('SECRET_KEY')

client = boto3.client(
    's3',
    aws_access_key_id=ACCESS_ID,
    aws_secret_access_key=SECRET_KEY,
)

continuation_token = ""
renamed = 0
while True:
    if continuation_token:
        results = client.list_objects_v2(Bucket=BUCKET, Prefix='', ContinuationToken=continuation_token)
    else:
        results = client.list_objects_v2(Bucket=BUCKET, Prefix='')
    for result in results['Contents']:
        if result['Key'].endswith('.peak'):
            client.delete_object(Bucket=BUCKET, Key=result['Key'])
            print("Deleted", result['Key'])
        elif '\\' in result['Key']:
            src = {'Bucket': BUCKET, 'Key': result['Key']}
            client.copy(Bucket=BUCKET, CopySource=src, Key=result['Key'].replace('\\', '/'))
            client.delete_object(Bucket=BUCKET, Key=result['Key'])
            print("Renamed", result['Key'].replace('\\', '/'))
            renamed += 1
    if not results['IsTruncated']:
        print("Not truncated; done")
        break
    else:
        print("Truncated, retrieving more results")
        continuation_token = results['NextContinuationToken']
print(renamed)
