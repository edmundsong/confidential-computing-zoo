#
# Copyright (c) 2021 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pickle
import argparse
import grpc
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor as Executor
import ipp_paillier as iphe
import homo_lr_pb2
import homo_lr_pb2_grpc

class HomoLRHost(object):
  def __init__(self, key_length, worker_num, secure):
    self.worker_num = worker_num
    self.weights_dict = {}
    self.updated_weights = None
    self.secure = secure
    self.pub_key = None
    self.pri_key = None
    if secure:
      self.generate_key(key_length)

  def generate_key(self, key_length=1024):
    self.pub_key, self.pri_key = iphe.PaillierKeypair.generate_keypair(key_length)

  def get_pubkey(self):
    return self.pub_key

  def get_prikey(self):
    return self.pri_key

  def aggregate_model(self, iter_n, weights):
    if iter_n in self.weights_dict:
      self.weights_dict[iter_n].append(weights)
    else:
      self.weights_dict[iter_n]=[weights]
    while len(self.weights_dict[iter_n]) < self.worker_num:
      continue
    self.updated_weights = (1 / self.worker_num) * np.sum(self.weights_dict[iter_n], axis=0)
    if self.secure:
      self.updated_weights = self.re_encrypt(self.updated_weights)
    return self.updated_weights

  def re_encrypt(self, values):
    pt = self.decrypt(values)
    return self.encrypt(pt)

  def encrypt(self, values):
    values = values.flatten()
    if isinstance(values, np.ndarray):
      w_ct = np.array([])
      v_len = len(values)
      i_end = (v_len // 8) * 8
      for i in range(0, i_end, 8):
        w_ct = np.append(w_ct, self.pub_key.encrypt(values[i : i + 8]))
      w_ct = np.append(w_ct, self.pub_key.encrypt(values[i_end:]))
      return w_ct.reshape((-1,1))
    elif isinstance(values, (int, float)):
      return self.pub_key.encrypt(values)
    else:
      print("Encryption error: data type is not supported.")
      exit(1)

  def decrypt(self, values):
    values = values.flatten()
    if isinstance(values, np.ndarray):
      w_ct = np.array([])
      v_len = len(values)
      i_end = (v_len // 8) * 8
      for i in range(0, i_end, 8):
        w_ct = np.append(w_ct, self.pri_key.decrypt(values[i : i + 8]))
      w_ct = np.append(w_ct, self.pri_key.decrypt(values[i_end:]))
      return w_ct
    elif isinstance(values, iphe.PaillierEncryptedNumber):
      return self.pri_key.decrypt(values)
    else:
      print("Decryption error: data type is not supported.")
      exit(1)
  
  def validate(self, x, y):
    w = None
    m = x.shape[0]
    x = np.concatenate((np.ones((m,1)),x), axis = 1)
    loss = np.nan
    if self.secure:
      w = self.decrypt(self.updated_weights)
    else:
      w = self.updated_weights.flatten()
    y_pred = self.sigmoid(np.dot(x, w))
    if not (0 in y_pred or 1 in y_pred):
      loss = (-1/m) * np.sum((np.multiply(y, np.log(y_pred)) + np.multiply((1 - y), np.log(1 - y_pred))))
    y_pred[y_pred < 0.5] = 0
    y_pred[y_pred >= 0.5] = 1
    acc = np.sum(y_pred == y) / m
    return acc, loss

  def sigmoid(self, x):
    return 1 / (1 + np.exp(-x))

class AggregateServicer(homo_lr_pb2_grpc.HostServicer):
    def __init__(self, key_length, worker_num, validate_set, secure):
      self.host = HomoLRHost(key_length, worker_num, secure)
      self.dataset = validate_set
      self.worker_num = worker_num
      self.finished = 0

    def GetPubKey(self, request, context):
      pubkey = pickle.dumps(self.host.get_pubkey())
      return homo_lr_pb2.KeyReply(key=pubkey)

    def AggregateModel(self, request, context):
      weights = pickle.loads(request.weights)
      updated_weights = self.host.aggregate_model(request.iter_n, weights)
      updated_w_pb = pickle.dumps(updated_weights)
      return homo_lr_pb2.WeightsReply(updated_weights=updated_w_pb)

    def Validate(self, request, context):
      if self.dataset is not None:
        x, y = parse_dataset(self.dataset)
        accuracy, loss = self.host.validate(x, y)
        return homo_lr_pb2.ValidateReply(acc=accuracy, loss=loss)
      else:
        return homo_lr_pb2.ValidateReply(acc=0, loss=0)

    def Finish(self, request, context):
      self.finished += 1
      if self.finished == self.worker_num:
        server.stop(5)
      return homo_lr_pb2.Empty()

def parse_dataset(dataset):
  data_array = pd.read_csv(dataset).to_numpy()
  x = data_array[:, 2:]
  y = data_array[:, 1].astype('int32')
  return x, y

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--key-length', type=int, default=1024, help='Bit length of PHE key')
  parser.add_argument('--worker-num', type=int, required=True, help='The numbers of workers in HFL')
  parser.add_argument('--validate-set', help='CSV format validation data')
  parser.add_argument('--secure', default=True, help='Enable PHE or not')
  args = parser.parse_args()
  server = grpc.server(Executor(max_workers=10))
  servicer = AggregateServicer(args.key_length, args.worker_num, args.validate_set, args.secure)
  homo_lr_pb2_grpc.add_HostServicer_to_server(servicer, server)
  server.add_insecure_port('[::]:50051')
  server.start()
  server.wait_for_termination()
