#!/usr/bin/env python3
"""
Create Lambda layer with dependencies
"""
import os
import subprocess
import zipfile
import boto3

def create_lambda_layer():
    """Create Lambda layer zip with requests dependency"""
    
    # Create layer directory structure
    layer_dir = "lambda-layer"
    python_dir = os.path.join(layer_dir, "python")
    
    os.makedirs(python_dir, exist_ok=True)
    
    # Install requests to layer directory
    subprocess.run([
        "pip", "install", "requests", "-t", python_dir
    ], check=True)
    
    # Create zip file
    zip_path = "lambda-layer.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(layer_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, layer_dir)
                zipf.write(file_path, arcname)
    
    print(f"✅ Created {zip_path}")
    
    # Upload to S3
    s3 = boto3.client('s3')
    
    # Get bucket name from stack outputs
    cf = boto3.client('cloudformation')
    response = cf.describe_stacks(StackName='Hackathon-Hunter-Stack')
    outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0]['Outputs']}
    bucket_name = outputs['S3BucketName']
    
    s3.upload_file(zip_path, bucket_name, 'lambda-layer.zip')
    print(f"✅ Uploaded to S3: {bucket_name}/lambda-layer.zip")
    
    # Cleanup
    import shutil
    shutil.rmtree(layer_dir)
    os.remove(zip_path)
    
    print("✅ Layer ready for deployment")

if __name__ == "__main__":
    create_lambda_layer()