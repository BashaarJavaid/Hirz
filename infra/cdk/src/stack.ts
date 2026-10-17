import { fileURLToPath } from 'node:url';
import {
  Stack, ArnFormat, IgnoreMode, CfnOutput, CfnParameter, Duration, RemovalPolicy, SecretValue, Tags,
  aws_bedrockagentcore as core, aws_cloudfront as cf, aws_cloudfront_origins as origins,
  aws_cognito as cognito, aws_ec2 as ec2, aws_ecs as ecs, aws_ecr_assets as assets,
  aws_elasticloadbalancingv2 as elb, aws_events as events, aws_events_targets as targets,
  aws_iam as iam, aws_kms as kms, aws_lambda as lambda, aws_logs as logs,
  aws_rds as rds, aws_s3 as s3, aws_scheduler as scheduler, aws_secretsmanager as secrets,
} from 'aws-cdk-lib';
import type { StackProps } from 'aws-cdk-lib';
import type { Construct } from 'constructs';

export class HirzStack extends Stack {
  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);
    Tags.of(this).add('Project', 'Hirz');
    Tags.of(this).add('Environment', 'item36');
    const desired = new CfnParameter(this, 'WorkerDesiredCount', {
      type: 'Number', default: 0, allowedValues: ['0', '1'],
    });
    const start = new CfnParameter(this, 'FixtureStart', {
      type: 'String', description: 'Fixed UTC acceptance start; preserve on every update.',
      allowedPattern: '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\+00:00$',
    });
    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.36.0.0/16'),
      availabilityZones: ['us-east-1a', 'us-east-1b'], natGateways: 1,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
    });
    const workerSg = new ec2.SecurityGroup(this, 'WorkerSecurity', { vpc });
    const albSg = new ec2.SecurityGroup(this, 'OriginSecurity', { vpc });
    // CloudFront creates its ENIs in this VPC; the ALB has no public address.
    albSg.addIngressRule(ec2.Peer.ipv4(vpc.vpcCidrBlock), ec2.Port.tcp(80));
    workerSg.addIngressRule(albSg, ec2.Port.tcp(8000));
    const database = new rds.DatabaseInstance(this, 'Database', {
      vpc, vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.of('16.15', '16') }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
      credentials: rds.Credentials.fromGeneratedSecret('hirz_setup'),
      databaseName: 'hirz_item36', allocatedStorage: 20, storageType: rds.StorageType.GP3,
      storageEncrypted: true, multiAz: false, publiclyAccessible: false,
      backupRetention: Duration.days(0), deleteAutomatedBackups: true,
      deletionProtection: false, removalPolicy: RemovalPolicy.DESTROY,
      parameterGroup: new rds.ParameterGroup(this, 'PostgresParameters', {
        engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.of('16.15', '16') }),
        parameters: { 'rds.force_ssl': '1' },
      }),
    });
    database.connections.allowDefaultPortFrom(workerSg);
    const appPassword = new secrets.Secret(this, 'DatabasePassword', {
      generateSecretString: { passwordLength: 40, excludePunctuation: true },
    });
    const audit = new secrets.Secret(this, 'AuditKey', {
      secretStringValue: SecretValue.unsafePlainText('UNINITIALIZED'),
    });
    const tickSecret = new secrets.Secret(this, 'TickSecret', {
      secretStringValue: SecretValue.unsafePlainText('UNINITIALIZED'),
    });
    const anchors = new s3.Bucket(this, 'Anchors', {
      encryption: s3.BucketEncryption.S3_MANAGED, enforceSSL: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, versioned: true,
      objectLockEnabled: true, objectLockDefaultRetention: s3.ObjectLockRetention.governance(Duration.days(30)),
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const signingKey = new kms.Key(this, 'CommandKey', {
      keySpec: kms.KeySpec.ECC_NIST_P256, keyUsage: kms.KeyUsage.SIGN_VERIFY,
      pendingWindow: Duration.days(7), removalPolicy: RemovalPolicy.DESTROY,
    });
    const synthetic = new secrets.Secret(this, 'SyntheticBackingSecret', {
      secretStringValue: SecretValue.unsafePlainText('{"api_key":"NONFUNCTIONAL-ITEM36-SYNTHETIC-CREDENTIAL"}'),
    });
    const identity = new core.CfnApiKeyCredentialProvider(this, 'SyntheticCredential', {
      name: 'hirz-item36-synthetic', apiKeySecretSource: 'EXTERNAL',
      apiKeySecretConfig: { secretId: synthetic.secretArn, jsonKey: 'api_key' },
    });
    const backingSecret = synthetic.secretArn;
    const worker = new iam.Role(this, 'WorkerRole', { assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com') });
    const setup = new iam.Role(this, 'SetupRole', { assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com') });
    const actions = new iam.Role(this, 'ActionsRole', {
      roleName: 'hirz-actions', assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
    });
    const mcp = new iam.Role(this, 'McpRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
        conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
      }),
    });
    const forbidden = new iam.PolicyStatement({
      effect: iam.Effect.DENY,
      actions: ['kms:Sign', 'bedrock-agentcore:GetResourceApiKey', 'bedrock-agentcore:GetResourceOauth2Token'], resources: ['*'],
    });
    for (const role of [worker, setup, mcp]) {
      role.addToPolicy(forbidden);
      role.addToPolicy(new iam.PolicyStatement({ effect: iam.Effect.DENY,
        actions: ['secretsmanager:GetSecretValue', 'secretsmanager:BatchGetSecretValue'], resources: [backingSecret] }));
    }
    mcp.addToPolicy(new iam.PolicyStatement({ effect: iam.Effect.DENY,
      actions: ['bedrock-agentcore:InvokeGateway', 'lambda:InvokeFunction', 'scheduler:CreateSchedule'], resources: ['*'] }));
    const workload = new core.CfnWorkloadIdentity(this, 'SignerIdentity', { name: 'hirz-item36-actions' });
    // Both resources are required: https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html
    actions.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:GetWorkloadAccessToken'], resources: [workload.attrWorkloadIdentityArn, this.formatArn({ service: 'bedrock-agentcore', resource: 'workload-identity-directory', resourceName: 'default' })] }));
    signingKey.grant(actions, 'kms:Sign');
    actions.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:GetResourceApiKey'], resources: [identity.attrCredentialProviderArn, workload.attrWorkloadIdentityArn, this.formatArn({ service: 'bedrock-agentcore', resource: 'token-vault', resourceName: 'default' }), this.formatArn({ service: 'bedrock-agentcore', resource: 'workload-identity-directory', resourceName: 'default' })] }));
    actions.addToPolicy(new iam.PolicyStatement({ actions: ['secretsmanager:GetSecretValue'], resources: [backingSecret] }));
    anchors.grantPut(worker);
    for (const role of [worker, setup]) {
      for (const secret of [appPassword, audit, tickSecret]) secret.grantRead(role);
    }
    audit.grantWrite(setup);
    tickSecret.grantWrite(setup);
    database.secret!.grantRead(setup);
    const pool = new cognito.UserPool(this, 'Users', { selfSignUpEnabled: false, removalPolicy: RemovalPolicy.DESTROY });
    const humanScopes = ['read', 'plan', 'act', 'verify'].map(scopeName => new cognito.ResourceServerScope({ scopeName, scopeDescription: scopeName }));
    const humanResource = pool.addResourceServer('HumanScopes', { identifier: 'hirz', scopes: humanScopes });
    const human = pool.addClient('Human', {
      generateSecret: false, accessTokenValidity: Duration.minutes(5),
      oAuth: { flows: { authorizationCodeGrant: true }, callbackUrls: ['http://localhost:8765/callback'],
        scopes: [cognito.OAuthScope.OPENID, ...humanScopes.map(s => cognito.OAuthScope.resourceServer(humanResource, s))] },
      preventUserExistenceErrors: true,
    });
    const invoke = new cognito.ResourceServerScope({ scopeName: 'invoke', scopeDescription: 'Invoke Gateway' });
    const gatewayResource = pool.addResourceServer('GatewayScope', { identifier: 'hirz-gateway', scopes: [invoke] });
    const machine = pool.addClient('Machine', {
      generateSecret: true, accessTokenValidity: Duration.minutes(5),
      oAuth: { flows: { clientCredentials: true }, scopes: [cognito.OAuthScope.resourceServer(gatewayResource, invoke)] },
    });
    const machineSecret = new secrets.Secret(this, 'MachineSecret', { secretStringValue: SecretValue.unsafePlainText('UNINITIALIZED') });
    machineSecret.grantRead(worker);
    machineSecret.grantRead(setup);
    machineSecret.grantWrite(setup);
    setup.addToPolicy(new iam.PolicyStatement({ actions: ['cognito-idp:DescribeUserPoolClient'], resources: [pool.userPoolArn] }));
    pool.addDomain('LoginDomain', { cognitoDomain: { domainPrefix: 'hirz-item36-661550216013' } });
    const discovery = `https://cognito-idp.${this.region}.amazonaws.com/${pool.userPoolId}/.well-known/openid-configuration`;
    const root = fileURLToPath(new URL('../../../', import.meta.url));
    const image = new assets.DockerImageAsset(this, 'Image', { directory: root, platform: assets.Platform.LINUX_ARM64, ignoreMode: IgnoreMode.DOCKER, exclude: ["infra/cdk/cdk.out", "**/node_modules", ".git", ".env"] });
    image.repository.grantPull(mcp);
    const runtime = new core.CfnRuntime(this, 'Runtime', {
      agentRuntimeName: 'hirz_item36', roleArn: mcp.roleArn,
      agentRuntimeArtifact: { containerConfiguration: { containerUri: image.imageUri } },
      protocolConfiguration: 'MCP', networkConfiguration: { networkMode: 'PUBLIC' },
      authorizerConfiguration: { customJwtAuthorizer: { discoveryUrl: discovery, allowedClients: [human.userPoolClientId] } },
      environmentVariables: { HIRZ_AWS_ROLE: 'mcp', HIRZ_LLM: 'off' },
    });
    const runtimeLog = new logs.LogGroup(this, 'RuntimeLog', {
      logGroupName: `/aws/bedrock-agentcore/runtimes/${runtime.attrAgentRuntimeId}-DEFAULT`,
      retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY,
    });
    mcp.addToPolicy(new iam.PolicyStatement({ actions: ['logs:CreateLogStream', 'logs:PutLogEvents', 'logs:DescribeLogStreams'], resources: [this.formatArn({ service: 'logs', resource: 'log-group', resourceName: '/aws/bedrock-agentcore/runtimes/hirz_item36-*:*', arnFormat: ArnFormat.COLON_RESOURCE_NAME })] }));
    // CloudFormation owns log-group creation and retention; Runtime may discover and publish to it.
    mcp.addToPolicy(new iam.PolicyStatement({ actions: ['logs:DescribeLogGroups'], resources: [this.formatArn({ service: 'logs', resource: 'log-group', resourceName: '*', arnFormat: ArnFormat.COLON_RESOURCE_NAME })] }));
    mcp.addToPolicy(new iam.PolicyStatement({ actions: ['logs:PutResourcePolicy'], resources: [this.formatArn({ service: 'logs', resource: 'log-group', resourceName: '/aws/bedrock-agentcore/runtimes/hirz_item36-*', arnFormat: ArnFormat.COLON_RESOURCE_NAME })] }));
    runtime.node.addDependency(mcp);
    void runtimeLog;
    const engine = new core.CfnPolicyEngine(this, 'PolicyEngine', { name: 'hirz_item36' });
    new core.CfnMemory(this, 'Memory', { name: 'hirz_item36', eventExpiryDuration: 3, memoryStrategies: [] });
    const code = lambda.Code.fromAsset(fileURLToPath(new URL('../../../hirz/aws/lambdas', import.meta.url)));
    const actionLog = new logs.LogGroup(this, 'ActionLog', { retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY });
    const signer = new lambda.Function(this, 'Signer', {
      functionName: 'hirz-item36-actions', role: actions, code, handler: 'actions.handler',
      runtime: lambda.Runtime.PYTHON_3_12, architecture: lambda.Architecture.ARM_64,
      logGroup: actionLog, timeout: Duration.seconds(10),
    });
    const gatewayRole = new iam.Role(this, 'GatewayRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
        conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
      }),
    });
    signer.grantInvoke(gatewayRole);
    const gateway = new core.CfnGateway(this, 'Gateway', {
      name: 'hirz-item36', roleArn: gatewayRole.roleArn, protocolType: 'MCP', authorizerType: 'CUSTOM_JWT',
      authorizerConfiguration: { customJwtAuthorizer: { discoveryUrl: discovery, allowedClients: [machine.userPoolClientId], allowedScopes: ['hirz-gateway/invoke'] } },
      policyEngineConfiguration: { arn: engine.attrPolicyEngineArn, mode: 'LOG_ONLY' },
    });
    gatewayRole.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock-agentcore:AuthorizeAction', 'bedrock-agentcore:PartiallyAuthorizeActions', 'bedrock-agentcore:GetPolicyEngine'], resources: [engine.attrPolicyEngineArn, this.formatArn({ service: 'bedrock-agentcore', resource: 'gateway', resourceName: 'hirz-item36-*' })] }));
    const gatewayLog = new logs.LogGroup(this, 'GatewayLog', { logGroupName: `/aws/bedrock-agentcore/gateways/${gateway.attrGatewayIdentifier}`, retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY });
    gatewayRole.addToPolicy(new iam.PolicyStatement({ actions: ['logs:CreateLogStream', 'logs:PutLogEvents'], resources: [this.formatArn({ service: 'logs', resource: 'log-group', resourceName: '/aws/bedrock-agentcore/gateways/hirz-item36-*:*', arnFormat: ArnFormat.COLON_RESOURCE_NAME })] }));
    void gatewayLog;
    gateway.node.addDependency(gatewayRole);
    new core.CfnGatewayTarget(this, 'UnavailableTool', {
      gatewayIdentifier: gateway.attrGatewayIdentifier, name: 'boundary',
      credentialProviderConfigurations: [{ credentialProviderType: 'GATEWAY_IAM_ROLE' }],
      targetConfiguration: { mcp: { lambda: { lambdaArn: signer.functionArn, toolSchema: {
        inlinePayload: [{ name: 'boundary_unavailable', description: 'AWS action enforcement is not connected.', inputSchema: { type: 'object', properties: {}, required: [] } }],
      } } } },
    });
    const alb = new elb.ApplicationLoadBalancer(this, 'Origin', {
      vpc, internetFacing: false, securityGroup: albSg,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }, idleTimeout: Duration.seconds(70),
    });
    const listener = alb.addListener('Http', { port: 80, open: false });
    const distribution = new cf.Distribution(this, 'Https', {
      defaultBehavior: {
        origin: origins.VpcOrigin.withApplicationLoadBalancer(alb, { protocolPolicy: cf.OriginProtocolPolicy.HTTP_ONLY, readTimeout: Duration.seconds(60) }),
        cachePolicy: cf.CachePolicy.CACHING_DISABLED, originRequestPolicy: cf.OriginRequestPolicy.ALL_VIEWER,
        allowedMethods: cf.AllowedMethods.ALLOW_ALL, viewerProtocolPolicy: cf.ViewerProtocolPolicy.HTTPS_ONLY,
      },
      errorResponses: [403, 404, 500, 502, 503, 504].map(httpStatus => ({ httpStatus, ttl: Duration.seconds(0) })),
    });
    const origin = `https://${distribution.distributionDomainName}`;
    const tickLog = new logs.LogGroup(this, 'TickLog', { retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY });
    const tick = new lambda.Function(this, 'Tick', {
      code, handler: 'tick.handler', runtime: lambda.Runtime.PYTHON_3_12, architecture: lambda.Architecture.ARM_64,
      timeout: Duration.seconds(75), logGroup: tickLog,
      environment: { HIRZ_TICK_URL: `${origin}/internal/tick`, HIRZ_TICK_SECRET: tickSecret.secretArn },
    });
    tickSecret.grantRead(tick);
    const group = new scheduler.CfnScheduleGroup(this, 'Schedules', { name: 'hirz-item36' });
    const scheduleRole = new iam.Role(this, 'ScheduleRole', { assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com', {
      conditions: { StringEquals: { 'aws:SourceAccount': this.account }, ArnEquals: { 'aws:SourceArn': group.attrArn } },
    }) });
    tick.grantInvoke(scheduleRole);
    new events.Rule(this, 'RecoveryTick', { schedule: events.Schedule.rate(Duration.minutes(1)), targets: [new targets.LambdaFunction(tick, { retryAttempts: 2, maxEventAge: Duration.minutes(2) })] });
    worker.addToPolicy(new iam.PolicyStatement({ actions: ['scheduler:ListSchedules'], resources: ['*'] }));
    worker.addToPolicy(new iam.PolicyStatement({ actions: ['scheduler:GetSchedule', 'scheduler:CreateSchedule', 'scheduler:UpdateSchedule', 'scheduler:DeleteSchedule'], resources: [this.formatArn({ service: 'scheduler', resource: 'schedule', resourceName: 'hirz-item36/*' })] }));
    worker.addToPolicy(new iam.PolicyStatement({ actions: ['iam:PassRole'], resources: [scheduleRole.roleArn], conditions: { StringEquals: { 'iam:PassedToService': 'scheduler.amazonaws.com' } } }));
    // Permissions are retained for later integration; acceptance never enables inference.
    worker.addToPolicy(new iam.PolicyStatement({ actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'], resources: [
      'arn:aws:bedrock:us-*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0',
      'arn:aws:bedrock:us-*::foundation-model/amazon.nova-lite-v1:0',
      this.formatArn({ service: 'bedrock', resource: 'inference-profile', resourceName: 'us.anthropic.claude-haiku-4-5-20251001-v1:0' }),
      this.formatArn({ service: 'bedrock', resource: 'inference-profile', resourceName: 'us.amazon.nova-lite-v1:0' }),
    ] }));
    const cluster = new ecs.Cluster(this, 'Cluster', { vpc });
    const environment = {
      HIRZ_AWS_ROLE: 'worker', HIRZ_LLM: 'off', HIRZ_DATABASE_HOST: database.dbInstanceEndpointAddress,
      HIRZ_DATABASE_NAME: 'hirz_item36', HIRZ_DATABASE_SECRET: appPassword.secretArn,
      HIRZ_AUDIT_SECRET: audit.secretArn, HIRZ_TICK_SECRET: tickSecret.secretArn,
      HIRZ_COMPANION_ORIGIN: origin, HIRZ_COMPANION_RP_ID: distribution.distributionDomainName,
      HIRZ_FIXTURE_START: start.valueAsString, HIRZ_SCHEDULE_GROUP: group.ref,
      HIRZ_TICK_ARN: tick.functionArn, HIRZ_SCHEDULE_ROLE: scheduleRole.roleArn,
      HIRZ_COMMAND_KEY: signingKey.keyArn, HIRZ_IDENTITY_ARN: identity.attrCredentialProviderArn,
      HIRZ_IDENTITY_SECRET: backingSecret,
      AWS_DEFAULT_REGION: this.region, OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1',
    };
    const workerLog = new logs.LogGroup(this, 'WorkerLog', { retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY });
    const task = new ecs.FargateTaskDefinition(this, 'WorkerTask', {
      cpu: 256, memoryLimitMiB: 512, taskRole: worker,
      runtimePlatform: { cpuArchitecture: ecs.CpuArchitecture.ARM64, operatingSystemFamily: ecs.OperatingSystemFamily.LINUX },
    });
    task.addContainer('hirz', { image: ecs.ContainerImage.fromDockerImageAsset(image), environment,
      command: ['python', '-m', 'hirz.aws'], logging: ecs.LogDrivers.awsLogs({ logGroup: workerLog, streamPrefix: 'worker' }),
      portMappings: [{ containerPort: 8000 }],
    });
    const service = new ecs.FargateService(this, 'Worker', {
      cluster, taskDefinition: task, desiredCount: desired.valueAsNumber, assignPublicIp: false,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }, securityGroups: [workerSg],
      minHealthyPercent: 0, maxHealthyPercent: 100, circuitBreaker: { rollback: true },
    });
    listener.addTargets('Worker', { port: 8000, targets: [service], deregistrationDelay: Duration.seconds(80), healthCheck: { path: '/health' } });
    const init = new ecs.FargateTaskDefinition(this, 'SetupTask', {
      cpu: 256, memoryLimitMiB: 512, taskRole: setup,
      runtimePlatform: { cpuArchitecture: ecs.CpuArchitecture.ARM64, operatingSystemFamily: ecs.OperatingSystemFamily.LINUX },
    });
    init.addContainer('hirz', { image: ecs.ContainerImage.fromDockerImageAsset(image),
      environment: { ...environment, HIRZ_MASTER_SECRET: database.secret!.secretArn, HIRZ_USER_POOL: pool.userPoolId, HIRZ_MACHINE_CLIENT: machine.userPoolClientId, HIRZ_MACHINE_SECRET: machineSecret.secretArn },
      command: ['python', '-m', 'hirz.aws.bootstrap'], logging: ecs.LogDrivers.awsLogs({ logGroup: workerLog, streamPrefix: 'setup' }),
    });
    for (const [name, value] of Object.entries({
      Origin: origin, Cluster: cluster.clusterArn, WorkerService: service.serviceName,
      WorkerTask: task.taskDefinitionArn, SetupTask: init.taskDefinitionArn, WorkerSecurity: workerSg.securityGroupId,
      PrivateSubnets: vpc.privateSubnets.map(s => s.subnetId).join(','),
      AuditSecret: audit.secretArn, TickSecret: tickSecret.secretArn, CommandKey: signingKey.keyArn,
      IdentityProvider: identity.attrCredentialProviderArn, IdentitySecret: backingSecret,
      SignerRole: actions.roleArn, AnchorBucket: anchors.bucketName, Runtime: runtime.attrAgentRuntimeArn,
      Gateway: gateway.attrGatewayUrl, UserPool: pool.userPoolId, HumanClient: human.userPoolClientId,
      ActionsLog: actionLog.logGroupName, WorkerLog: workerLog.logGroupName, ImageRepository: image.repository.repositoryName, TickFunction: tick.functionName, ScheduleGroup: group.ref,
    })) new CfnOutput(this, name + 'Output', { value }).overrideLogicalId(name);
  }
}
