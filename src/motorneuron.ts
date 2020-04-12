// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Neuron } from './neuron';
import { Qualia } from './qualia';

export class MotorNeuron extends Neuron {
  readonly type: Neuron.Type = 'motor';
  async tick(input: Qualia.Matrix): Promise<Qualia.Matrix> {
    return input;
  }
}
