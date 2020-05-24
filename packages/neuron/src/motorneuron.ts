// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Neuron } from './neuron';

export class MotorNeuron extends Neuron {
  readonly type: Neuron.Type = 'motor';
  async fire(input: Neuron.Matrix): Promise<Neuron.Matrix> {
    return input;
  }
}
