// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Neuron } from './neuron';

export class SensoryNeuron extends Neuron {
  readonly type: Neuron.Type = 'sensory';
  async tick(input: Neuron.Matrix): Promise<Neuron.Matrix> {
    return input;
  }
}
