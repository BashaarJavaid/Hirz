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
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', { GenerateSecret: false, AllowedOAuthFlows: ['code'], AccessTokenValidity: 5, CallbackURLs: ['http://localhost:8765/callback', { Ref: 'CompanionCallbackUrl' }] });
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', { GenerateSecret: true, AllowedOAuthFlows: ['client_credentials'], AllowedOAuthScopes: [Match.anyValue()] });
    template.hasResourceProperties('AWS::BedrockAgentCore::Gateway', { AuthorizerType: 'CUSTOM_JWT', PolicyEngineConfiguration: Match.objectLike({ Mode: 'LOG_ONLY' }) });
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      ProtocolConfiguration: 'MCP', AuthorizerConfiguration: { CustomJWTAuthorizer: Match.objectLike({ AllowedClients: [Match.anyValue()] }) },
      NetworkConfiguration: { NetworkMode: 'VPC', NetworkModeConfig: { SecurityGroups: [Match.anyValue()], Subnets: [Match.anyValue(), Match.anyValue()] } },
      RequestHeaderConfiguration: { RequestHeaderAllowlist: ['Authorization'] },
      EnvironmentVariables: Match.objectLike({ HIRZ_AWS_ROLE: 'mcp', HIRZ_LLM: 'off', HIRZ_RUNTIME_RESOURCE: { Ref: 'RuntimeResource' }, HIRZ_HUMAN_CLIENT: Match.anyValue(), HIRZ_DATABASE_SECRET: Match.anyValue(), HIRZ_AUDIT_SECRET: Match.anyValue(), HIRZ_POLICY_ENGINE: Match.anyValue() }),
    });
    template.hasResourceProperties('AWS::BedrockAgentCore::GatewayTarget', { TargetConfiguration: { Mcp: { Lambda: { LambdaArn: Match.anyValue(), ToolSchema: { InlinePayload: Match.arrayWith([Match.objectLike({ Name: 'governance_approve_action', OutputSchema: Match.objectLike({ Required: ['approved', 'ttl_minutes', 'executed'] }) })]) } } } } });
    template.hasResourceProperties('AWS::BedrockAgentCore::Memory', { EventExpiryDuration: 3, MemoryStrategies: [
      { UserPreferenceMemoryStrategy: { Name: 'MemberPreferences', NamespaceTemplates: ['/hirz/{actorId}/preferences/'] } },
      { SemanticMemoryStrategy: { Name: 'MemberFacts', NamespaceTemplates: ['/hirz/{actorId}/semantic/'] } },
    ] });
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
  it('scopes policy publication to the worker and the shared engine', () => {
    const publishers = Object.entries(template.findResources('AWS::IAM::Policy')).filter(([, p]) => p.Properties.PolicyDocument.Statement.some((s: { Effect: string; Action: string | string[] }) => s.Effect === 'Allow' && [s.Action].flat().includes('bedrock-agentcore:CreatePolicy')));
    expect(publishers).toHaveLength(1);
    expect(publishers[0][0]).toMatch(/^WorkerRole/);
    const grants = publishers[0][1].Properties.PolicyDocument.Statement.filter((s: { Action: string | string[] }) => [s.Action].flat().includes('bedrock-agentcore:CreatePolicy'));
    expect(grants[0].Resource).not.toBe('*');
    expect(JSON.stringify(grants[0].Resource)).toContain('PolicyEngine');
    template.hasResourceProperties('AWS::XRay::TransactionSearchConfig', { IndexingPercentage: 0 });
    expect(Object.values(template.findResources('AWS::Logs::LogGroup')).some(g => g.Properties.LogGroupName === 'aws/spans')).toBe(false);
    template.hasResourceProperties('AWS::Logs::LogGroup', { LogGroupName: '/aws/application-signals/data', RetentionInDays: 7 });
    expect(JSON.stringify(template.findResources('AWS::Logs::ResourcePolicy'))).toContain('PolicySignals');
    template.hasResourceProperties('AWS::Logs::DeliverySource', { LogType: 'TRACES', Name: 'hirz-item36-policy-traces' });
  });
  it('gives Runtime database and audit access without worker or Gateway authority', () => {
    const policy = Object.entries(template.findResources('AWS::IAM::Policy')).find(([id]) => id.startsWith('McpRoleDefaultPolicy'))![1];
    const allows = policy.Properties.PolicyDocument.Statement.filter((s: { Effect: string }) => s.Effect === 'Allow');
    const reads = allows.filter((s: { Action: string | string[] }) => [s.Action].flat().includes('secretsmanager:GetSecretValue'));
    expect(reads).toHaveLength(2);
    expect(JSON.stringify(reads)).toContain('DatabasePassword');
    expect(JSON.stringify(reads)).toContain('AuditKey');
    expect(JSON.stringify(reads)).not.toMatch(/MachineSecret|TickSecret|BackingSecret/);
    expect(allows.flatMap((s: { Action: string | string[] }) => s.Action)).not.toEqual(expect.arrayContaining(['bedrock-agentcore:InvokeGateway']));
    const runtime = Object.values(template.findResources('AWS::BedrockAgentCore::Runtime'))[0];
    const security = runtime.Properties.NetworkConfiguration.NetworkModeConfig.SecurityGroups[0];
    const [databaseId, database] = Object.entries(template.findResources('AWS::RDS::DBInstance'))[0];
    const port = { 'Fn::GetAtt': [databaseId, 'Endpoint.Port'] };
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', { FromPort: port, ToPort: port, IpProtocol: 'tcp', SourceSecurityGroupId: security, GroupId: database.Properties.VPCSecurityGroups[0] });
    expect(JSON.stringify(runtime.Properties.EnvironmentVariables)).not.toContain('MachineSecret');
    expect(template.toJSON().Parameters.RuntimeResource.Default).toBe('');
    for (const task of Object.values(template.findResources('AWS::ECS::TaskDefinition'))) {
      for (const name of ['HIRZ_RUNTIME_RESOURCE', 'HIRZ_COGNITO_ISSUER', 'HIRZ_HUMAN_CLIENT']) {
        expect(task.Properties.ContainerDefinitions[0].Environment).toContainEqual({ Name: name, Value: runtime.Properties.EnvironmentVariables[name] });
      }
      expect(task.Properties.ContainerDefinitions[0].Environment).toContainEqual({ Name: 'HIRZ_ACCOUNT_LINK_CALLBACK', Value: { Ref: 'CompanionCallbackUrl' } });
    }
  });
  it('limits Memory access to the Runtime and worker on the configured resource', () => {
    const [id] = Object.keys(template.findResources('AWS::BedrockAgentCore::Memory'));
    const operations = ['bedrock-agentcore:CreateEvent', 'bedrock-agentcore:ListEvents', 'bedrock-agentcore:ListMemoryRecords'];
    const grants = Object.entries(template.findResources('AWS::IAM::Policy')).flatMap(([policy, p]) =>
      p.Properties.PolicyDocument.Statement.filter((s: { Effect: string; Action: string | string[] }) => s.Effect === 'Allow' && [s.Action].flat().some(a => operations.includes(a))).map((s: { Action: string[]; Resource: unknown }) => ({ policy, ...s })));
    expect(grants).toHaveLength(2);
    expect(grants.map(g => g.policy).sort()).toEqual([
      expect.stringMatching(/^McpRoleDefaultPolicy/), expect.stringMatching(/^WorkerRoleDefaultPolicy/),
    ]);
    for (const grant of grants) {
      expect(grant.Action).toEqual(operations);
      expect(grant.Resource).toEqual({ 'Fn::GetAtt': [id, 'MemoryArn'] });
    }
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      EnvironmentVariables: Match.objectLike({ HIRZ_MEMORY_ID: { 'Fn::GetAtt': [id, 'MemoryId'] } }),
    });
    for (const task of Object.values(template.findResources('AWS::ECS::TaskDefinition'))) {
      expect(task.Properties.ContainerDefinitions[0].Environment).toContainEqual({ Name: 'HIRZ_MEMORY_ID', Value: { 'Fn::GetAtt': [id, 'MemoryId'] } });
    }
  });
  it('permits token counting only for the worker and the configured Haiku model', () => {
    const policies = Object.entries(template.findResources('AWS::IAM::Policy'));
    const counters = policies.filter(([, p]) => p.Properties.PolicyDocument.Statement.some((s: { Action: string | string[] }) => [s.Action].flat().includes('bedrock:CountTokens')));
    expect(counters).toHaveLength(1);
    expect(counters[0][0]).toMatch(/^WorkerRoleDefaultPolicy/);
    expect(counters[0][1].Properties.PolicyDocument.Statement).toContainEqual({ Effect: 'Allow', Action: 'bedrock:CountTokens', Resource: 'arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0' });
    for (const [id, policy] of policies.filter(([id]) => !id.startsWith('WorkerRoleDefaultPolicy'))) {
      expect(policy.Properties.PolicyDocument.Statement.flatMap((s: { Action: string | string[] }) => s.Action), id).not.toEqual(expect.arrayContaining(['bedrock:InvokeModel']));
    }
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
