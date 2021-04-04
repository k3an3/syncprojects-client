from abc import ABC, abstractmethod

import boto3


class AWSAuth(ABC):
    @abstractmethod
    def authenticate(self):
        pass


class CognitoAuth(AWSAuth):
    def __init__(self):
        super().__init__()
        self._client = boto3.client('cognito-idp', region_name=self.region_name)
        self.client = None
        self.id_token = None
        self.identity_id = None
        self.aws_credentials = None
        self.bucket = None
        self.authenticate()

    def authenticate(self):
        self.id_token = self.get_cognito_id_token(
            self.username, self.refresh_token,
            self.device_key, self.client_id
        )
        self.identity_id = self.get_identity_id(
            self.account_id, self.identity_pool_id,
            self.provider_name, self.id_token
        )
        self.aws_credentials = self.get_credentials(
            self.identity_id, self.provider_name, self.id_token
        )
        self.client = boto3.client(
            's3',
            aws_access_key_id=self.aws_credentials['AccessKeyId'],
            aws_secret_access_key=self.aws_credentials['SecretKey'],
            aws_session_token=self.aws_credentials['SessionToken'],
        )

    def get_cognito_id_token(self, username, refresh_token,
                             device_key, client_id):
        response = self._client.initiate_auth(
            AuthFlow='REFRESH_TOKEN',
            AuthParameters={
                'USERNAME': username,
                'REFRESH_TOKEN': refresh_token,
                'DEVICE_KEY': device_key
            },
            ClientId=client_id
        )
        return response['AuthenticationResult']['IdToken']

    def get_identity_id(self, account_id, identity_pool_id,
                        provider_name, id_token):
        creds = self._client.get_id(
            AccountId=account_id, IdentityPoolId=identity_pool_id,
            Logins={provider_name: id_token}
        )
        return creds['IdentityId']

    def get_credentials(self, identity_id, provider_name, id_token):
        creds = self._client.get_credentials_for_identity(
            IdentityId=identity_id,
            Logins={provider_name: id_token},
        )
        return creds['Credentials']
