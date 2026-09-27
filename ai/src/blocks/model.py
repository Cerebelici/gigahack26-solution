"""Small segmentation net. Input is a color-corrected RGB chip, output is vine logits."""

from __future__ import annotations

import torch
from torch import nn


class _ConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class BlockUNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.e1 = _ConvBlock(3, 16)
        self.e2 = _ConvBlock(16, 32)
        self.e3 = _ConvBlock(32, 64)
        self.pool = nn.MaxPool2d(2)
        self.bottleneck = _ConvBlock(64, 128)
        self.u3 = nn.ConvTranspose2d(128, 64, 2, stride=2)
        self.d3 = _ConvBlock(128, 64)
        self.u2 = nn.ConvTranspose2d(64, 32, 2, stride=2)
        self.d2 = _ConvBlock(64, 32)
        self.u1 = nn.ConvTranspose2d(32, 16, 2, stride=2)
        self.d1 = _ConvBlock(32, 16)
        self.head = nn.Conv2d(16, 1, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        s1 = self.e1(x)
        s2 = self.e2(self.pool(s1))
        s3 = self.e3(self.pool(s2))
        b = self.bottleneck(self.pool(s3))
        x = self.d3(torch.cat([self.u3(b), s3], dim=1))
        x = self.d2(torch.cat([self.u2(x), s2], dim=1))
        x = self.d1(torch.cat([self.u1(x), s1], dim=1))
        return self.head(x)
