import { App, DefaultStackSynthesizer } from 'aws-cdk-lib';
import { HirzStack } from './stack.ts';

const app = new App();
new HirzStack(app, 'HirzItem36', {
  env: { account: '661550216013', region: 'us-east-1' },
  synthesizer: new DefaultStackSynthesizer({ qualifier: 'hirzitem36' }),
});
