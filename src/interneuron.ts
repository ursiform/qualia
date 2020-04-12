// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Neuron } from './neuron';
import { Qualia } from './qualia';

export class Interneuron extends Neuron {
  readonly type: Neuron.Type = 'interneuron';
  async tick(input: Qualia.Matrix): Promise<Qualia.Matrix> {
    return input;
  }
}
