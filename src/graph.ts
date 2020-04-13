// (c) Copyright Afshin T. Darian 2020. All Rights Reserved.

import { UUID } from '@lumino/coreutils';
import { IObservableDisposable } from '@lumino/disposable';
import { ISignal, Signal } from '@lumino/signaling';

export class Graph<T extends IObservableDisposable>
  implements IObservableDisposable {
  get disposed(): ISignal<this, void> {
    return this._disposed;
  }

  get isDisposed(): boolean {
    return this._isDisposed;
  }

  add(node: T, key = UUID.uuid4()) {
    const { nodes } = this;
    if (nodes.has(key)) {
      return;
    }
    nodes.set(key, { node, in: new Map(), out: new Map() });
  }

  dispose() {
    if (this._isDisposed) {
      return;
    }
    this._isDisposed = true;
    this._disposed.emit(undefined);
  }

  link(a: string, b: string) {
    const { nodes } = this;
    if (!nodes.has(a)) {
      throw new ReferenceError(`Graph#link: ${a} does not exist.`);
    }
    if (!nodes.has(b)) {
      throw new ReferenceError(`Graph#link: ${b} does not exist.`);
    }
    nodes.get(a)!.out.set(b);
    nodes.get(b)!.in.set(a);
  }

  unlink(a: string, b: string) {
    const { nodes } = this;
    if (!nodes.has(a)) {
      throw new ReferenceError(`Graph#unlink: ${a} does not exist.`);
    }
    if (!nodes.has(b)) {
      throw new ReferenceError(`Graph#unlink: ${b} does not exist.`);
    }
    nodes.get(a)!.out.delete(b);
    nodes.get(b)!.in.delete(a);
  }

  protected nodes = new Map<
    string,
    {
      node: T;
      in: Map<string, void>;
      out: Map<string, void>;
    }
  >();

  private _disposed = new Signal<this, void>(this);
  private _isDisposed = false;
}
