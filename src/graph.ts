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
    const { graph } = this;

    if (graph.has(key)) {
      console.warn(`Graph#add: ${key} already exists.`);
      return;
    }

    graph.set(key, { node, in: new Map(), out: new Map() });
    node.disposed.connect(() => {
      this.remove(key);
    }, this);
  }

  dispose() {
    if (this._isDisposed) {
      return;
    }
    this._isDisposed = true;
    this._disposed.emit(undefined);
  }

  link(a: string, b: string) {
    const { graph } = this;

    if (!graph.has(a)) {
      throw new ReferenceError(`Graph#link: ${a} does not exist.`);
    }
    if (!graph.has(b)) {
      throw new ReferenceError(`Graph#link: ${b} does not exist.`);
    }

    graph.get(a)!.out.set(b);
    graph.get(b)!.in.set(a);
  }

  remove(key: string) {
    const { graph } = this;

    if (!graph.has(key)) {
      console.warn(`Graph#remove: ${key} does not exist.`);
      return;
    }

    const node = graph.get(key)!;

    node.in.forEach((_, peer) => {
      this.unlink(key, peer);
    });
    node.out.forEach((_, peer) => {
      this.unlink(key, peer);
    });
    graph.delete(key);
    Signal.disconnectBetween(node, this);
  }

  unlink(a: string, b: string) {
    const { graph } = this;

    if (!graph.has(a)) {
      throw new ReferenceError(`Graph#unlink: ${a} does not exist.`);
    }
    if (!graph.has(b)) {
      throw new ReferenceError(`Graph#unlink: ${b} does not exist.`);
    }

    const one = graph.get(a)!;
    const two = graph.get(b)!;

    one.in.delete(b);
    one.out.delete(b);
    two.in.delete(a);
    two.out.delete(a);
  }

  protected graph = new Map<
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
