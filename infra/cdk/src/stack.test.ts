import { App, DefaultStackSynthesizer } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { describe, it, expect } from 'vitest';
import { HirzStack } from './stack.ts';

const app = new App({ context: { 'availability-zones:account=661550216013:region=us-east-1': ['us-east-1a', 'us-east-1b'] } });
const stack = new HirzStack(app, 'HirzItem36', {
  env: { account: '661550216013', region: 'us-east-1' },
  synthesizer: new DefaultStackSynthesizer({ qualifier: 'hirzitem36' }),
});
const template = Template.fromStack(stack);
const resources = template.toJSON().Resources;

describe('item 36 acceptance infrastructure', () => {
  it('keeps the bootstrap cold and limits resources', () => {
    template.hasParameter('WorkerDesiredCount', { Default: 0, AllowedValues: ['0', '1'] });
    template.hasResourceProperties('AWS::ECS::Service', { DesiredCount: { Ref: 'WorkerDesiredCount' }, NetworkConfiguration: { AwsvpcConfiguration: { AssignPublicIp: 'DISABLED', Subnets: Match.anyValue(), SecurityGroups: Match.anyValue() } }, DeploymentConfiguration: Match.objectLike({ MaximumPercent: 100, MinimumHealthyPercent: 0 }) });
    template.resourceCountIs('AWS::ECS::Service', 1);
    for (const task of Object.values(template.findResources('AWS::ECS::TaskDefinition'))) {
      expect(task.Properties).toMatchObject({ Cpu: '256', Memory: '512', RuntimePlatform: { CpuArchitecture: 'ARM64', OperatingSystemFamily: 'LINUX' } });
      expect(task.Properties.ContainerDefinitions[0].Environment).toContainEqual({ Name: 'HIRZ_LLM', Value: 'off' });
    }
    template.resourceCountIs('AWS::ApplicationAutoScaling::ScalableTarget', 0);
    // Client-secret retrieval belongs to the explicit setup task, not an extra CDK provider Lambda.
    template.resourceCountIs('AWS::Lambda::Function', 2);
    template.resourceCountIs('AWS::Route53::HostedZone', 0);
    template.hasResource('AWS::RDS::DBInstance', { DeletionPolicy: 'Delete', Properties: Match.objectLike({ EngineVersion: '16.15', DBInstanceClass: 'db.t4g.micro', AllocatedStorage: '20', StorageType: 'gp3', StorageEncrypted: true, MultiAZ: false, PubliclyAccessible: false, BackupRetentionPeriod: 0 }) });
  });
  it('uses private application networking and uncached HTTPS', () => {
    template.hasResourceProperties('AWS::EC2::VPC', { CidrBlock: '10.36.0.0/16' });
    template.resourceCountIs('AWS::EC2::NatGateway', 1);
    template.resourceCountIs('AWS::EC2::EIP', 1);
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', { IpProtocol: 'tcp', FromPort: 80, ToPort: 80, SourcePrefixListId: 'pl-3b927c52', GroupId: { 'Fn::GetAtt': ['OriginSecurityA7C4F0AE', 'GroupId'] } });
    template.hasResourceProperties('AWS::ElasticLoadBalancingV2::LoadBalancer', { Scheme: 'internal', LoadBalancerAttributes: Match.arrayWith([{ Key: 'idle_timeout.timeout_seconds', Value: '70' }]) });
    template.hasResourceProperties('AWS::CloudFront::VpcOrigin', { VpcOriginEndpointConfig: Match.objectLike({ OriginProtocolPolicy: 'http-only' }) });
    template.hasResourceProperties('AWS::CloudFront::Distribution', { DistributionConfig: Match.objectLike({
      DefaultCacheBehavior: Match.objectLike({ ViewerProtocolPolicy: 'https-only', CachePolicyId: '4135ea2d-6df8-44a3-9df3-4b5a84be39ad', OriginRequestPolicyId: '216adef6-5c7f-47e4-b989-5492eafa07d3' }),
      Origins: Match.arrayWith([Match.objectLike({ VpcOriginConfig: Match.objectLike({ OriginReadTimeout: 60 }) })]),
    }) });
  });
  it('keeps all acceptance boundaries explicit', () => {
    template.hasResourceProperties('AWS::Cognito::UserPool', { AdminCreateUserConfig: { AllowAdminCreateUserOnly: true } });
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', { GenerateSecret: false, AllowedOAuthFlows: ['code'], AccessTokenValidity: 5, CallbackURLs: ['http://localhost:8765/callback'] });
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', { GenerateSecret: true, AllowedOAuthFlows: ['client_credentials'], AllowedOAuthScopes: [Match.anyValue()] });
    template.hasResourceProperties('AWS::BedrockAgentCore::Gateway', { AuthorizerType: 'CUSTOM_JWT', PolicyEngineConfiguration: Match.objectLike({ Mode: 'LOG_ONLY' }) });
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', { ProtocolConfiguration: 'MCP', AuthorizerConfiguration: { CustomJWTAuthorizer: Match.objectLike({ AllowedClients: [Match.anyValue()] }) }, EnvironmentVariables: { HIRZ_AWS_ROLE: 'mcp', HIRZ_LLM: 'off' } });
    template.hasResourceProperties('AWS::BedrockAgentCore::GatewayTarget', { TargetConfiguration: { Mcp: { Lambda: { LambdaArn: Match.anyValue(), ToolSchema: { InlinePayload: Match.arrayWith([Match.objectLike({ Name: 'governance_approve_action', OutputSchema: Match.objectLike({ Required: ['approved', 'ttl_minutes', 'executed'] }) })]) } } } } });
    template.hasResourceProperties('AWS::BedrockAgentCore::Memory', { EventExpiryDuration: 3, MemoryStrategies: [] });
    template.hasResourceProperties('AWS::KMS::Key', { KeySpec: 'ECC_NIST_P256', KeyUsage: 'SIGN_VERIFY', PendingWindowInDays: 7 });
    template.hasResourceProperties('AWS::S3::Bucket', { ObjectLockConfiguration: { ObjectLockEnabled: 'Enabled', Rule: { DefaultRetention: { Mode: 'GOVERNANCE', Days: 30 } } } });
    for (const log of Object.values(template.findResources('AWS::Logs::LogGroup'))) expect(log.Properties.RetentionInDays).toBe(7);
    template.hasResourceProperties('AWS::Events::Rule', { ScheduleExpression: 'rate(1 minute)' });
    template.hasResourceProperties('AWS::Lambda::Function', { Handler: 'tick.handler', Timeout: 75 });
  });
  it('denies both credential paths and signing outside the actions role', () => {
    for (const prefix of ['WorkerRole', 'McpRole', 'SetupRole']) {
      const policy = Object.entries(resources).find(([id, r]) => id.startsWith(prefix + 'DefaultPolicy') && (r as { Type: string }).Type === 'AWS::IAM::Policy')![1] as { Properties: { PolicyDocument: { Statement: { Effect: string; Action: string | string[] }[] } } };
      const denied = policy.Properties.PolicyDocument.Statement.filter(s => s.Effect === 'Deny').flatMap(s => s.Action);
      expect(denied).toEqual(expect.arrayContaining(['kms:Sign', 'bedrock-agentcore:GetResourceApiKey', 'bedrock-agentcore:GetResourceOauth2Token', 'secretsmanager:GetSecretValue', 'secretsmanager:BatchGetSecretValue']));
    }
    const signingPolicies = Object.entries(template.findResources('AWS::IAM::Policy')).filter(([, p]) => p.Properties.PolicyDocument.Statement.some((s: { Effect: string; Action: string | string[] }) => s.Effect === 'Allow' && [s.Action].flat().includes('kms:Sign')));
    expect(signingPolicies.map(([id]) => id)).toHaveLength(1);
    expect(signingPolicies[0][0]).toMatch(/^ActionsRole/);
  });
  it('synthesizes without network lookups and without dependency cycles', () => {
    expect(app.synth().manifest.missing ?? []).toEqual([]);
    const visit = (id: string, trail: string[]) => {
      if (!resources[id]) return;
      expect(trail).not.toContain(id);
      const r = resources[id];
      const dependencies = [...JSON.stringify(r).matchAll(/"Ref":"([^"]+)"|"Fn::GetAtt":\["([^"]+)"/g)].map(m => m[1] || m[2]);
      for (const next of new Set([...dependencies, ...(r.DependsOn ?? [])])) visit(next, [...trail, id]);
    };
    for (const id of Object.keys(resources)) visit(id, []);
  });
});
