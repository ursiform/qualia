// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { Qualia } from './qualia';

export abstract class Neuron {
  abstract type: Neuron.Type;
  abstract async tick(input: Qualia.Matrix): Promise<Qualia.Matrix>;
}

export namespace Neuron {
  export type Type = 'interneuron' | 'motor' | 'sensory';
}
