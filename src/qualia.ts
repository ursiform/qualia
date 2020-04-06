// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

export namespace Qualia {
  export const version = '0.0.2';
  export type Input = number[];
  export type Neuron = {
    inputs: Input[];
    outputs: Output[];
  };
  export type Output = number[];
}
